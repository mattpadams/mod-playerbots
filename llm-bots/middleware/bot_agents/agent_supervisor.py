"""Manages the lifecycle of active bot agents.

Coordinates polling, state diffing, event routing, and agent invocations.
"""

from __future__ import annotations

import asyncio

import structlog

from bot_agents.bot_agent import BotAgent
from core.bot_registry import BotRegistry
from core.event_bus import EventBus
from core.game_client import BotSnapshot, GameClient
from game.events import IdleTickEvent
from game.state_differ import diff
from memory.memory_manager import MemoryManager
from providers.base import LLMProvider
from scheduler.cost_controller import CostController

logger = structlog.get_logger()


class AgentSupervisor:
    """Owns all active BotAgent instances and runs the poll + dispatch loop."""

    def __init__(
        self,
        game_client: GameClient,
        registry: BotRegistry,
        event_bus: EventBus,
        memory_manager: MemoryManager,
        cost_controller: CostController,
        provider: LLMProvider,
        tick_interval: float = 3.0,
    ) -> None:
        self._game = game_client
        self._registry = registry
        self._bus = event_bus
        self._memory = memory_manager
        self._cost = cost_controller
        self._provider = provider
        self._tick_interval = tick_interval

        self._agents: dict[int, BotAgent] = {}
        self._last_snapshots: dict[int, BotSnapshot] = {}
        self._stop_event = asyncio.Event()
        self._traces: list = []  # recent traces for the dashboard

    @property
    def traces(self) -> list:
        return self._traces[-100:]  # keep last 100

    def get_agent(self, guid: int) -> BotAgent | None:
        return self._agents.get(guid)

    async def start(self) -> None:
        """Start the supervisor poll loop."""
        self._stop_event.clear()
        logger.info("supervisor.started", tick_interval=self._tick_interval)
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.error("supervisor.tick_error", error=str(exc))
            # Sleep but wake immediately if stop is signaled
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._tick_interval
                )
            except asyncio.TimeoutError:
                pass  # normal — tick interval elapsed, loop continues

    async def stop(self) -> None:
        self._stop_event.set()
        logger.info("supervisor.stopped")

    async def _tick(self) -> None:
        """One poll cycle: query state, diff, route events, run agents."""
        profiles = self._registry.all_elevated()
        if not profiles:
            return

        # Ensure agents exist for all elevated bots
        for profile in profiles:
            if profile.guid not in self._agents:
                self._agents[profile.guid] = BotAgent(
                    profile=profile,
                    memory_manager=self._memory,
                    cost_controller=self._cost,
                    provider=self._provider,
                )
                logger.info("supervisor.agent_created", guid=profile.guid, name=profile.name)

        # Remove agents for demoted bots
        active_guids = {p.guid for p in profiles}
        for guid in list(self._agents.keys()):
            if guid not in active_guids:
                del self._agents[guid]
                self._last_snapshots.pop(guid, None)
                self._bus.remove_bot(guid)
                logger.info("supervisor.agent_removed", guid=guid)

        # Poll state for all active bots concurrently
        guid_list = list(self._agents.keys())
        snapshot_results = await asyncio.gather(
            *[self._game.get_bot_state(guid) for guid in guid_list],
            return_exceptions=True,
        )
        snapshots: dict[int, BotSnapshot] = {}
        for guid, result in zip(guid_list, snapshot_results):
            if isinstance(result, Exception):
                logger.warning("supervisor.poll_failed", guid=guid, error=str(result))
            else:
                snapshots[guid] = result

        # Diff and route events, then run agents concurrently
        agent_tasks = []
        for guid, agent in self._agents.items():
            if self._registry.is_degraded(guid):
                continue
            new_snap = snapshots.get(guid)
            if not new_snap:
                continue

            agent.update_snapshot(new_snap)
            old_snap = self._last_snapshots.get(guid)

            # Generate events from state diff
            events = diff(old_snap, new_snap, bot_name=agent.name)
            self._last_snapshots[guid] = new_snap

            # Also check for any events pushed to the bus (future: HTTP push)
            bus_events = self._bus.drain(guid)
            events.extend(bus_events)

            # If no events, maybe send an idle tick for proactive behavior
            if not events:
                agent._idle_counter += 1
                if agent._idle_counter >= 10:
                    agent._idle_counter = 0
                    events.append(
                        IdleTickEvent(
                            bot_guid=guid,
                            bot_name=agent.name,
                            idle_seconds=self._tick_interval * 10,
                        )
                    )

            # Record all events and handle the most important one via LLM
            for event in events:
                await agent.record_event(event)

            if events:
                best_event = self._pick_best_event(events)
                agent_tasks.append(self._run_agent(agent, best_event))

        # Run agent invocations concurrently
        if agent_tasks:
            results = await asyncio.gather(*agent_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("supervisor.agent_error", error=str(result))

    async def _run_agent(self, agent: BotAgent, event) -> None:
        trace = await agent.handle_event(event)
        if trace:
            self._traces.append(trace)

    def _pick_best_event(self, events: list) -> object:
        """Pick the most important event to pass to the LLM."""
        priority = {
            "chat_received": 0,
            "group_invite": 1,
            "bot_died": 2,
            "combat_start": 3,
            "zone_changed": 4,
            "idle_tick": 5,
        }
        events.sort(key=lambda e: priority.get(e.event_type.value, 99))
        return events[0]
