"""Manages the lifecycle of active bot agents.

Coordinates polling, state diffing, event routing, and agent invocations.
"""
from __future__ import annotations

import asyncio
from collections import deque

import structlog

from bot_agents.bot_agent import BotAgent, is_invocation_event
from core.bot_registry import BotRegistry
from core.command_executor import CommandExecutor
from core.event_bus import EventBus
from core.game_client import BotSnapshot, GameClient
from game.events import IdleTickEvent
from game.state_differ import diff
from memory.memory_manager import MemoryManager
from providers import get_default_model
from providers.base import LLMProvider
from scheduler.cost_controller import CostController

logger = structlog.get_logger()

_EVENT_PRIORITY: dict[str, int] = {
    "chat_received": 0, "group_invite": 1, "bot_died": 2,
    "combat_start": 3, "zone_changed": 4, "idle_tick": 5,
}


class AgentSupervisor:
    """Owns all active BotAgent instances and runs the poll + dispatch loop."""

    def __init__(
        self,
        game_client: GameClient,
        registry: BotRegistry,
        event_bus: EventBus,
        executor: CommandExecutor,
        memory_manager: MemoryManager,
        cost_controller: CostController,
        provider: LLMProvider,
        tick_interval: float = 3.0,
    ) -> None:
        self._game = game_client
        self._registry = registry
        self._bus = event_bus
        self._executor = executor
        self._memory = memory_manager
        self._cost = cost_controller
        self._provider = provider
        self._tick_interval = tick_interval

        self._agents: dict[int, BotAgent] = {}
        self._last_snapshots: dict[int, BotSnapshot] = {}
        self._stop_event = asyncio.Event()
        self._traces: deque = deque(maxlen=100)

    @property
    def traces(self) -> list:
        return list(self._traces)

    def get_agent(self, guid: int) -> BotAgent | None:
        return self._agents.get(guid)

    async def start(self) -> None:
        self._stop_event.clear()
        logger.info("supervisor.started", tick_interval=self._tick_interval)
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.error("supervisor.tick_error", error=str(exc))
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._tick_interval
                )
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop_event.set()
        # Tear down all sessions
        await asyncio.gather(
            *(agent.stop() for agent in self._agents.values()),
            return_exceptions=True,
        )
        self._agents.clear()
        logger.info("supervisor.stopped")

    async def _tick(self) -> None:
        profiles = self._registry.all_elevated()

        # Add agents for newly-elevated bots
        for profile in profiles:
            if profile.guid in self._agents:
                continue
            agent = BotAgent(
                profile=profile,
                executor=self._executor,
                memory_manager=self._memory,
                cost_controller=self._cost,
                provider=self._provider,
                default_model=get_default_model(),
            )
            try:
                await agent.start()
            except Exception as exc:
                logger.error("supervisor.agent_start_failed",
                             guid=profile.guid, error=str(exc))
                continue
            self._agents[profile.guid] = agent
            logger.info("supervisor.agent_created",
                        guid=profile.guid, name=profile.name)

        # Remove agents for demoted bots (close their sessions)
        active_guids = {p.guid for p in profiles}
        stale = [g for g in self._agents if g not in active_guids]
        for guid in stale:
            agent = self._agents.pop(guid)
            await agent.stop()
            self._last_snapshots.pop(guid, None)
            self._bus.remove_bot(guid)
            logger.info("supervisor.agent_removed", guid=guid)

        if not self._agents:
            return

        # Poll state for all active bots concurrently
        guid_list = list(self._agents.keys())
        snapshot_results = await asyncio.gather(
            *[self._game.get_bot_state(guid) for guid in guid_list],
            return_exceptions=True,
        )
        snapshots: dict[int, BotSnapshot] = {}
        for guid, result in zip(guid_list, snapshot_results):
            if isinstance(result, Exception):
                logger.warning("supervisor.poll_failed",
                               guid=guid, error=str(result))
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
            events = diff(old_snap, new_snap, bot_name=agent.name)
            self._last_snapshots[guid] = new_snap
            events.extend(self._bus.drain(guid))

            if not events:
                agent._idle_counter += 1
                if agent._idle_counter >= 10:
                    agent._idle_counter = 0
                    events.append(IdleTickEvent(
                        bot_guid=guid, bot_name=agent.name,
                        idle_seconds=self._tick_interval * 10,
                    ))

            for event in events:
                await agent.record_event(event)

            best = self._pick_best_event(events)
            if best is not None:
                agent_tasks.append(self._run_agent(agent, best))

        if agent_tasks:
            results = await asyncio.gather(*agent_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("supervisor.agent_error", error=str(result))

    async def _run_agent(self, agent: BotAgent, event) -> None:
        trace = await agent.handle_event(event)
        if trace:
            self._traces.append(trace)

    def _pick_best_event(self, events: list) -> object | None:
        """Select the highest-priority event that warrants an LLM call."""
        candidates = [e for e in events if is_invocation_event(e)]
        if not candidates:
            return None
        candidates.sort(key=lambda e: _EVENT_PRIORITY.get(e.event_type.value, 99))
        return candidates[0]
