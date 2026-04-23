"""Per-bot agent powered by the LLM provider abstraction.

Each elevated bot gets one ``BotAgent`` instance.  Tools are registered
on the shared provider — the bot agent only provides context (system
prompt + game state + memories) and the bot's GUID which the LLM passes
to tools as an input parameter.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog

from api import metrics
from combat.context import CombatContext, CombatContextBuilder
from core import player_policy
from core.bot_registry import BotProfile, BotRegistry
from core.config import settings
from core.game_client import BotSnapshot
from dungeons.coordinator import DungeonContext
from game.event_policy import EventPolicy, get_policy
from game.events import (
    AddsSpawnedEvent,
    AdminForceSayEvent,
    BossEngagedEvent,
    BossPhaseChangedEvent,
    ChatReceivedEvent,
    DungeonEnteredEvent,
    EventType,
    GameEvent,
    IdleTickEvent,
    LootRollStartedEvent,
    PartyMemberDiedEvent,
    PartyQuestProgressEvent,
    PartyWipeEvent,
    CraftRequestedEvent,
)
from memory.memory_manager import MemoryManager
from personality.loader import load_profile
from party.models import PartyState
from personality.prompt_builder import build_context_message, build_system_prompt
from providers.base import EventType as ProviderEventType, LLMProvider, ProviderConfig
from scheduler.cost_controller import CostController

logger = structlog.get_logger()


@dataclass
class AgentTrace:
    """Observability record for a single agent invocation."""

    bot_guid: int
    bot_name: str
    event_type: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    response_preview: str = ""
    cost_usd: float = 0.0


class BotAgent:
    """Runs an LLM agent for a single bot.

    Does NOT own tools — those are registered on the shared provider.
    The system prompt includes the bot's GUID so the LLM knows
    which value to pass to tool ``bot_guid`` parameters.
    """

    def __init__(
        self,
        profile: BotProfile,
        memory_manager: MemoryManager,
        cost_controller: CostController,
        provider: LLMProvider,
        combat_context_builder: CombatContextBuilder | None = None,
        registry: BotRegistry | None = None,
    ) -> None:
        self._profile = profile
        self._memory = memory_manager
        self._cost = cost_controller
        self._provider = provider
        self._combat_ctx_builder = combat_context_builder
        # Registry is optional so existing tests that pass only the bare
        # minimum still build; rate-limit degradation short-circuits when
        # the registry is absent.
        self._registry = registry

        self._system_prompt = self._compose_system_prompt()

        self._recent_events: list[str] = []
        self._last_snapshot: BotSnapshot | None = None
        self._idle_counter: int = 0

    @property
    def guid(self) -> int:
        return self._profile.guid

    @property
    def name(self) -> str:
        return self._profile.name

    def update_snapshot(self, snapshot: BotSnapshot) -> None:
        self._last_snapshot = snapshot

    def _compose_system_prompt(self) -> str:
        """Render the persona prompt plus the GUID-binding footer.

        Kept private so __init__ and reload_system_prompt can't drift.
        """
        base = build_system_prompt(
            self._profile.personality, self._profile.name
        )
        return base + (
            f"\n\nIMPORTANT: Your bot GUID is {self._profile.guid}. "
            f"You MUST pass bot_guid={self._profile.guid} to every tool call."
        )

    def reload_system_prompt(self) -> None:
        """Rebuild the cached system prompt from the current profile.

        Called after an admin hot-swaps the bot's personality so the
        running agent picks up the new persona without being demoted.
        """
        self._system_prompt = self._compose_system_prompt()

    async def record_event(self, event: GameEvent) -> None:
        """Add a human-readable event summary to the recent events buffer."""
        summary = _event_summary(event)
        if summary:
            self._recent_events.append(summary)
            if len(self._recent_events) > 20:
                self._recent_events = self._recent_events[-20:]

        await self._memory.maybe_store_event(self.guid, self.name, event)

    def maybe_emit_idle(self, idle_seconds: float) -> IdleTickEvent | None:
        """Increment the idle counter; emit an ``IdleTickEvent`` every
        Nth consecutive idle tick, ``None`` otherwise.

        Gated by ``settings.proactive_enabled`` (global default off) AND
        a per-personality ``proactive_enabled: true`` in the YAML profile.
        Both must be true — the global flag is a kill switch, the
        personality flag opts specific characters into initiative.
        """
        if not settings.proactive_enabled:
            return None
        try:
            profile_data = load_profile(self._profile.personality)
        except Exception as exc:  # YAML error, missing file, etc.
            logger.warning(
                "bot_agent.proactive_profile_load_failed",
                personality=self._profile.personality,
                error=str(exc),
            )
            return None
        if not profile_data.get("proactive_enabled", False):
            return None

        self._idle_counter += 1
        if self._idle_counter >= settings.proactive_idle_ticks:
            self._idle_counter = 0
            return IdleTickEvent(
                bot_guid=self.guid,
                bot_name=self.name,
                idle_seconds=idle_seconds,
            )
        return None

    async def handle_event(
        self,
        event: GameEvent,
        party_state: PartyState | None = None,
        dungeon_context: DungeonContext | None = None,
    ) -> AgentTrace | None:
        """Decide whether to invoke the LLM and execute the response.

        ``party_state`` is an immutable snapshot of the bot's party for
        this tick; the supervisor injects it (never fetched from inside
        the agent).
        """
        policy = get_policy(event.event_type)
        if not policy.invoke_llm:
            return None

        # Global admin kill switch: drops every LLM call instantly so the
        # classic playerbot AI runs unsupervised. Cheaper than a rate-
        # limit check and must come first.
        if settings.llm_kill_switch:
            return None

        # Per-player opt-out: owner flipped ``llm_enabled`` off on their
        # ``player_settings`` row. ``bots_enabled=false`` likewise skips
        # LLM invocation — the party logoff checker will take the bot
        # offline on its own cadence.
        if player_policy.is_llm_disabled(self.guid) or player_policy.is_bot_disabled(
            self.guid
        ):
            return None

        if not self._cost.check_rate_limit(self.guid):
            logger.debug("bot_agent.rate_limited", bot_guid=self.guid)
            return None

        model = self._cost.select_model(policy.model_tier)
        if model is None:
            logger.debug("bot_agent.budget_exhausted", bot_guid=self.guid)
            return None

        # Build context message
        triggering_text = _event_summary(event)
        player_name = self._extract_player_name(event)
        memories = await self._memory.get_context(
            bot_guid=self.guid,
            situation_query=triggering_text,
            player_name=player_name,
        )

        snapshot = self._last_snapshot or BotSnapshot(guid=self.guid)

        # Fetch rich combat context only when the policy asks for it
        # (e.g. COMBAT_START, HEALTH_CRITICAL). Failure here never
        # blocks the LLM call — we degrade to the lighter prompt.
        combat_ctx: CombatContext | None = None
        if policy.needs_combat_context and self._combat_ctx_builder is not None:
            try:
                combat_ctx = await self._combat_ctx_builder.build(
                    self.guid, snapshot
                )
            except Exception as exc:
                logger.warning(
                    "bot_agent.combat_context_failed",
                    bot_guid=self.guid,
                    error=str(exc),
                )

        # Only include party context when the policy asks for it — most
        # events don't need it and the tokens aren't free.
        effective_party_state = party_state if policy.needs_party_context else None

        context_msg = build_context_message(
            snapshot=snapshot,
            recent_events=self._recent_events,
            memories=memories,
            triggering_event=triggering_text,
            combat_context=combat_ctx,
            party_state=effective_party_state,
            dungeon_context=dungeon_context,
        )

        config = ProviderConfig(model=model, system_prompt=self._system_prompt)

        trace = AgentTrace(
            bot_guid=self.guid,
            bot_name=self.name,
            event_type=event.event_type.value,
            model=model,
        )

        start = time.monotonic()
        # Tracks whether any ERROR event was surfaced during the stream so
        # we don't mark the call "successful" and reset the 429 streak.
        errored = False
        try:
            async for response_event in self._provider.query(context_msg, config):
                if response_event.type == ProviderEventType.NARRATIVE:
                    text = response_event.data.get("text", "")
                    if text and not trace.response_preview:
                        trace.response_preview = text[:200]
                elif response_event.type == ProviderEventType.TOOL_CALL:
                    trace.tool_calls.append(response_event.data.get("name", ""))
                elif response_event.type == ProviderEventType.USAGE:
                    trace.tokens_in = response_event.data.get("tokens_in", 0)
                    trace.tokens_out = response_event.data.get("tokens_out", 0)
                    trace.cost_usd = self._cost.record_usage(
                        model, trace.tokens_in, trace.tokens_out
                    )
                    # Per-bot attribution (previously unwritten fields)
                    self._profile.total_tokens_in += trace.tokens_in
                    self._profile.total_tokens_out += trace.tokens_out
                    self._profile.total_cost_usd += trace.cost_usd
                    # Prometheus counters
                    metrics.llm_tokens_total.labels(direction="input").inc(
                        trace.tokens_in
                    )
                    metrics.llm_tokens_total.labels(direction="output").inc(
                        trace.tokens_out
                    )
                elif response_event.type == ProviderEventType.ERROR:
                    err_text = response_event.data.get("text", "")
                    logger.error(
                        "bot_agent.provider_error",
                        bot_guid=self.guid,
                        error=err_text,
                    )
                    errored = True
                    self._maybe_handle_rate_limit(err_text)

            trace.latency_ms = (time.monotonic() - start) * 1000
            self._cost.record_latency(trace.latency_ms)
            self._profile.total_llm_calls += 1
            if trace.tool_calls:
                self._profile.last_llm_action = trace.tool_calls[-1]
            elif trace.response_preview:
                self._profile.last_llm_action = "say"

            # Prometheus: count + latency
            metrics.llm_calls_total.labels(
                bot_guid=str(self.guid),
                event_type=event.event_type.value,
                model=model,
            ).inc()
            metrics.llm_latency_seconds.labels(model=model).observe(
                trace.latency_ms / 1000.0
            )

            logger.info(
                "bot_agent.invocation_complete",
                bot_guid=self.guid,
                event_type=event.event_type.value,
                model=model,
                latency_ms=round(trace.latency_ms),
                tool_calls=trace.tool_calls,
            )

        except Exception as exc:
            logger.error(
                "bot_agent.invocation_failed",
                bot_guid=self.guid,
                event_type=event.event_type.value,
                latency_ms=round((time.monotonic() - start) * 1000),
                error=str(exc),
            )
            self._maybe_handle_rate_limit(str(exc))
            # Drop the trace on failure so zero-filled rows don't pollute
            # the dashboard feed / SQLite log.
            return None

        # Only count as "successful" when the stream produced no error
        # events — otherwise a streamed 429 would immediately undo its
        # own rate-limit bookkeeping.
        if not errored:
            self._cost.note_successful_call()
        return trace

    def _maybe_handle_rate_limit(self, text: str) -> None:
        """If the provider message looks like a rate-limit response, mark
        this bot degraded and tell the cost controller so the global
        circuit breaker can engage on repeat errors."""
        lowered = text.lower()
        if "429" not in text and "rate limit" not in lowered and "rate_limit" not in lowered:
            return
        self._cost.note_rate_limit_error()
        metrics.rate_limit_errors_total.labels(scope="bot").inc()
        if self._registry is not None:
            until = datetime.now(timezone.utc) + timedelta(
                seconds=settings.rate_limit_per_bot_backoff_seconds
            )
            self._registry.mark_degraded(self.guid, until)
        logger.warning(
            "bot_agent.rate_limit_backoff",
            bot_guid=self.guid,
            seconds=settings.rate_limit_per_bot_backoff_seconds,
        )

    def _extract_player_name(self, event: GameEvent) -> str | None:
        if isinstance(event, ChatReceivedEvent):
            return event.sender_name
        return None


# -- Extend _event_summary to handle admin-injected prompts --------------------


def _event_summary(event: GameEvent) -> str:
    """Convert a GameEvent to a human-readable one-line summary."""
    if isinstance(event, ChatReceivedEvent):
        return f'{event.sender_name} says ({event.channel}): "{event.message}"'
    if isinstance(event, AdminForceSayEvent):
        return f'[admin] Please react to: "{event.text}"'
    match event.event_type:
        case EventType.COMBAT_START:
            return f"Combat started with {getattr(event, 'target_name', 'unknown')}"
        case EventType.COMBAT_END:
            return "Combat ended."
        case EventType.BOT_DIED:
            return "You died."
        case EventType.BOT_REVIVED:
            return "You were revived."
        case EventType.HEALTH_CRITICAL:
            return f"Health critical: {getattr(event, 'hp_pct', '?')}%"
        case EventType.MANA_CRITICAL:
            return (
                f"Mana critical: {getattr(event, 'mana_pct', '?')}%. "
                "Call out for a mana break or conserve casts."
            )
        case EventType.ZONE_CHANGED:
            return f"Entered {getattr(event, 'new_zone', 'unknown zone')}"
        case EventType.TARGET_CHANGED:
            return f"New target: {getattr(event, 'new_target', 'none')}"
        case EventType.STRATEGY_CHANGED:
            return f"Strategy changed to: {getattr(event, 'new_strategy', '?')}"
        case EventType.IDLE_TICK:
            return "Nothing particular is happening. You are idle."
        case EventType.PARTY_QUEST_PROGRESS:
            e = event
            if isinstance(e, PartyQuestProgressEvent):
                return (
                    f"Party quest pickup: {e.picker_name or e.bot_name} now has "
                    f"{e.new_count}/{e.required} {e.item_name} "
                    f"({e.quest_name}). Consider broadcasting progress in party chat."
                )
            return "Party quest progress update."
        case EventType.LOOT_ROLL_STARTED:
            e = event
            if isinstance(e, LootRollStartedEvent):
                return (
                    f"Loot roll started on {e.item_name or e.item_link}. "
                    "You were chosen as the best recipient by party "
                    "arbitration. Decide need, greed, or pass (if you "
                    "want to hand the upgrade to a party member)."
                )
            return "Loot roll started."
        case EventType.DUNGEON_ENTERED:
            e = event
            if isinstance(e, DungeonEnteredEvent):
                return (
                    f"You zoned into {e.dungeon_name} ({e.difficulty}). "
                    f"Your role: {e.role}. Greet the party and settle in."
                )
            return "Zoned into a dungeon."
        case EventType.DUNGEON_EXITED:
            return "Left the dungeon."
        case EventType.BOSS_ENGAGED:
            e = event
            if isinstance(e, BossEngagedEvent):
                lead = " You are leading this fight." if e.is_leader else ""
                return f"Boss engaged: {e.boss_name}.{lead}"
            return "Boss engaged."
        case EventType.BOSS_DEFEATED:
            return "Boss defeated."
        case EventType.BOSS_PHASE_CHANGED:
            e = event
            if isinstance(e, BossPhaseChangedEvent):
                return (
                    f"{e.boss_name} transitioned to {e.phase_name or 'next phase'}. "
                    "Adjust tactics for the new phase."
                )
            return "Boss phase changed."
        case EventType.PARTY_MEMBER_DIED:
            e = event
            if isinstance(e, PartyMemberDiedEvent):
                return (
                    f"{e.dead_bot_name} ({e.dead_bot_role}) went down in "
                    f"{e.dungeon_name}. Call it out and coordinate a rescue or res."
                )
            return "A party member died."
        case EventType.PARTY_WIPE:
            e = event
            if isinstance(e, PartyWipeEvent):
                dead = ", ".join(e.dead_bot_names) or "everyone"
                return (
                    f"Party wipe in {e.dungeon_name}. Dead: {dead}. "
                    "As leader, acknowledge the wipe and suggest a different approach."
                )
            return "Party wiped."
        case EventType.ADDS_SPAWNED:
            e = event
            if isinstance(e, AddsSpawnedEvent):
                return (
                    f"Adds spawned: {e.delta} new enemies "
                    f"({e.previous_attacker_count} -> {e.new_attacker_count}). "
                    "Reassess target priority — who takes the adds?"
                )
            return "Adds spawned."
        case EventType.CRAFT_REQUESTED:
            e = event
            if isinstance(e, CraftRequestedEvent):
                src = e.requested_by or "the party"
                reason = f" ({e.reason})" if e.reason else ""
                return f"{src} needs you to craft {e.item_name}{reason}."
            return "Craft request."
        case _:
            return f"Event: {event.event_type.value}"
