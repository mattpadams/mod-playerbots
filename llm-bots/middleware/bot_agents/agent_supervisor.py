"""Manages the lifecycle of active bot agents.

Coordinates polling, state diffing, event routing, and agent invocations.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from api import metrics
from bot_agents.bot_agent import AgentTrace, BotAgent
from combat.context import CombatContextBuilder
from core.bot_registry import BotRegistry
from core.command_executor import CommandExecutor
from core.config import settings
from core.event_bus import EventBus
from core.game_client import BotSnapshot, GameClient
from core.trace_store import TraceStore
from dungeons.coordinator import DungeonCoordinator
from game.debounce import DebounceFilter
from game.event_policy import get_policy
from game.events import EventType
from game.state_differ import diff
from memory.memory_manager import MemoryManager
from party.coordinator import PartyCoordinator
from providers.base import LLMProvider
from scheduler.auto_elevator import AutoElevator
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
        trace_store: TraceStore | None = None,
        command_executor: CommandExecutor | None = None,
        auto_elevator: AutoElevator | None = None,
    ) -> None:
        self._game = game_client
        self._registry = registry
        self._bus = event_bus
        self._memory = memory_manager
        self._cost = cost_controller
        self._provider = provider
        self._tick_interval = tick_interval
        self._combat_ctx_builder = CombatContextBuilder(game_client)
        self._trace_store = trace_store
        self._auto_elevator = auto_elevator
        # Party coordinator is optional — main.py wires it with a command
        # executor. Tests that don't care about M4 coordination can skip it.
        self._party: PartyCoordinator | None = (
            PartyCoordinator(game_client, registry, command_executor)
            if command_executor is not None
            else None
        )
        # Dungeon coordinator runs regardless of command_executor — it
        # still emits events and resolves prompt context, just without
        # strategy activation when the executor is absent.
        self._dungeon = DungeonCoordinator(
            registry=registry, command_executor=command_executor
        )

        self._agents: dict[int, BotAgent] = {}
        self._last_snapshots: dict[int, BotSnapshot] = {}
        self._debounce_filters: dict[int, DebounceFilter] = {}
        self._stop_event = asyncio.Event()
        self._traces: list = []  # recent traces for the dashboard
        # SSE fan-out: each subscriber owns an asyncio.Queue; publishing
        # drops the oldest entry if a slow client fills the queue.
        self._trace_subscribers: list[asyncio.Queue[AgentTrace]] = []

    @property
    def traces(self) -> list:
        return self._traces[-100:]  # keep last 100

    @property
    def last_snapshots(self) -> dict[int, BotSnapshot]:
        return self._last_snapshots

    @property
    def party_coordinator(self) -> PartyCoordinator | None:
        return self._party

    @property
    def dungeon_coordinator(self) -> DungeonCoordinator:
        return self._dungeon

    def get_agent(self, guid: int) -> BotAgent | None:
        return self._agents.get(guid)

    # -- Trace SSE fan-out -----------------------------------------------------

    @property
    def trace_subscriber_count(self) -> int:
        return len(self._trace_subscribers)

    def subscribe_traces(self, maxsize: int = 64) -> asyncio.Queue[AgentTrace]:
        q: asyncio.Queue[AgentTrace] = asyncio.Queue(maxsize=maxsize)
        self._trace_subscribers.append(q)
        return q

    def unsubscribe_traces(self, queue: asyncio.Queue[AgentTrace]) -> None:
        try:
            self._trace_subscribers.remove(queue)
        except ValueError:
            pass

    def _broadcast_trace(self, trace: AgentTrace) -> None:
        for q in self._trace_subscribers:
            if q.full():
                try:
                    q.get_nowait()  # drop oldest for slow consumers
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(trace)
            except asyncio.QueueFull:
                pass

    async def start(self) -> None:
        """Start the supervisor poll loop."""
        self._stop_event.clear()
        logger.info("supervisor.started", tick_interval=self._tick_interval)
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.error("supervisor.tick_error", error=str(exc))
            # Sleep until tick interval elapses, but wake early if:
            #  - a push event arrives via the HTTP endpoint (wake_event)
            #  - the supervisor is asked to stop (stop_event)
            self._bus.clear_wake()
            wake = asyncio.create_task(self._bus.wake_event.wait())
            stop = asyncio.create_task(self._stop_event.wait())
            timer = asyncio.create_task(asyncio.sleep(self._tick_interval))
            done, pending = await asyncio.wait(
                {wake, stop, timer}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            # If stop was signaled, exit the loop on next iteration check

    async def stop(self) -> None:
        self._stop_event.set()
        logger.info("supervisor.stopped")

    async def _tick(self) -> None:
        """One poll cycle: query state, diff, route events, run agents."""
        tick_start = time.monotonic()
        # Auto-elevator first — may add/remove bots before we snapshot.
        if self._auto_elevator is not None:
            try:
                self._auto_elevator.reconcile()
            except Exception as exc:
                logger.warning("supervisor.auto_elevator_error", error=str(exc))

        profiles = self._registry.all_elevated()
        metrics.active_agents_gauge.set(len(profiles))
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
                    combat_context_builder=self._combat_ctx_builder,
                    registry=self._registry,
                )
                self._debounce_filters[profile.guid] = DebounceFilter()
                logger.info("supervisor.agent_created", guid=profile.guid, name=profile.name)

        # Remove agents for demoted bots
        active_guids = {p.guid for p in profiles}
        for guid in list(self._agents.keys()):
            if guid not in active_guids:
                del self._agents[guid]
                self._last_snapshots.pop(guid, None)
                self._debounce_filters.pop(guid, None)
                self._bus.remove_bot(guid)
                logger.info("supervisor.agent_removed", guid=guid)

        # Poll state for all active bots in batches so 50 bots don't hit
        # the TCP server (or the event loop) all at once.
        guid_list = list(self._agents.keys())
        snapshots: dict[int, BotSnapshot] = {}
        poll_results = await self._run_batched(
            [self._game.get_bot_state(guid) for guid in guid_list]
        )
        for guid, result in zip(guid_list, poll_results):
            if isinstance(result, Exception):
                logger.warning(
                    "supervisor.poll_failed", guid=guid, error=str(result)
                )
            else:
                snapshots[guid] = result

        # Party coordinator runs before per-bot event routing so its
        # queued events fold into this same tick.
        party_events_by_guid: dict[int, list] = {}
        if self._party is not None and snapshots:
            try:
                await self._party.update(snapshots)
            except Exception as exc:
                logger.warning("supervisor.party_update_failed", error=str(exc))
            for evt in self._party.pop_events():
                party_events_by_guid.setdefault(evt.bot_guid, []).append(evt)

        # Dungeon coordinator: detect instance transitions, push strategy
        # activation, queue enter/exit events for this tick.
        dungeon_events_by_guid: dict[int, list] = {}
        if snapshots:
            try:
                await self._dungeon.update(snapshots)
            except Exception as exc:
                logger.warning("supervisor.dungeon_update_failed", error=str(exc))
            for evt in self._dungeon.pop_events():
                dungeon_events_by_guid.setdefault(evt.bot_guid, []).append(evt)

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

            # Also check for any events pushed to the bus (HTTP push from C++)
            bus_events = self._bus.drain(guid)
            events.extend(bus_events)

            # Party-coordinator events (quest progress, craft requests,
            # loot-roll winner assignments).
            events.extend(party_events_by_guid.get(guid, []))

            # Dungeon enter/exit events for this bot.
            events.extend(dungeon_events_by_guid.get(guid, []))

            # Adds-spawn events detected by the CombatContextBuilder on
            # its most recent build for this bot. The builder doesn't
            # know the bot's name, so we stamp it here before routing.
            for evt in self._combat_ctx_builder.pop_events(guid):
                evt.bot_name = agent.name
                events.append(evt)

            # Apply per-bot debounce: drops events whose policy cooldown
            # has not yet elapsed (e.g. HEALTH_CRITICAL within 30s).
            events = self._debounce_filters[guid].filter(
                events, current_hp_pct=new_snap.hp_pct
            )

            # If no events, maybe emit an idle tick (every 10th idle cycle)
            if not events:
                idle = agent.maybe_emit_idle(self._tick_interval * 10)
                if idle is not None:
                    events.append(idle)

            # Record all events and handle the most important one via LLM
            for event in events:
                await agent.record_event(event)

            if events:
                best_event = self._pick_best_event(events)
                party_state = (
                    self._party.get_party_state(guid) if self._party else None
                )
                dungeon_ctx = self._dungeon.get_context_with_target(
                    guid, new_snap.target_name
                )
                agent_tasks.append(
                    self._run_agent(agent, best_event, party_state, dungeon_ctx)
                )

        # Run agent invocations in batches so the outbound LLM traffic
        # is staggered across the tick instead of firing in one wave.
        # Skip entirely if the cost controller's global breaker is open
        # — there is no point queuing calls that will return None.
        if agent_tasks and not self._cost.global_backoff_active:
            results = await self._run_batched(agent_tasks)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("supervisor.agent_error", error=str(result))
        metrics.tick_duration_seconds.observe(time.monotonic() - tick_start)

    async def _run_batched(self, coros: list) -> list:
        """Run ``coros`` chunked by ``tick_batch_size`` with a small sleep
        between batches. Returns results in input order; exceptions are
        captured (``return_exceptions=True``) so callers can classify.
        """
        batch_size = max(1, settings.tick_batch_size)
        spacing = max(0.0, settings.tick_batch_spacing_ms / 1000.0)
        out: list = []
        for i in range(0, len(coros), batch_size):
            chunk = coros[i : i + batch_size]
            out.extend(
                await asyncio.gather(*chunk, return_exceptions=True)
            )
            if spacing > 0 and i + batch_size < len(coros):
                await asyncio.sleep(spacing)
        return out

    async def _run_agent(
        self, agent: BotAgent, event, party_state=None, dungeon_context=None
    ) -> None:
        trace = await agent.handle_event(
            event, party_state=party_state, dungeon_context=dungeon_context
        )
        if not trace:
            return
        self._traces.append(trace)
        self._broadcast_trace(trace)
        if self._trace_store is not None:
            await self._trace_store.insert(
                bot_guid=trace.bot_guid,
                bot_name=trace.bot_name,
                event_type=trace.event_type,
                model=trace.model,
                tokens_in=trace.tokens_in,
                tokens_out=trace.tokens_out,
                cost_usd=trace.cost_usd,
                latency_ms=trace.latency_ms,
                tool_calls=list(trace.tool_calls),
                preview=trace.response_preview,
            )

    def _pick_best_event(self, events: list) -> object:
        """Pick the most important event to pass to the LLM.

        Uses ``EventPolicy.priority`` from the single source of truth in
        ``game/event_policy.py``. Lower priority value = more important.
        """
        events.sort(key=lambda e: get_policy(e.event_type).priority)
        return events[0]
