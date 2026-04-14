"""Per-bot agent powered by the LLM provider abstraction.

Each elevated bot gets one ``BotAgent`` instance.  Tools are registered
on the shared provider — the bot agent only provides context (system
prompt + game state + memories) and the bot's GUID which the LLM passes
to tools as an input parameter.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from core.bot_registry import BotProfile
from core.game_client import BotSnapshot
from game.events import ChatReceivedEvent, EventType, GameEvent
from memory.memory_manager import MemoryManager
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
    ) -> None:
        self._profile = profile
        self._memory = memory_manager
        self._cost = cost_controller
        self._provider = provider

        self._system_prompt = build_system_prompt(profile.personality, profile.name)
        # Append the bot GUID instruction so the LLM passes it to tools
        self._system_prompt += (
            f"\n\nIMPORTANT: Your bot GUID is {profile.guid}. "
            f"You MUST pass bot_guid={profile.guid} to every tool call."
        )

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

    async def record_event(self, event: GameEvent) -> None:
        """Add a human-readable event summary to the recent events buffer."""
        summary = _event_summary(event)
        if summary:
            self._recent_events.append(summary)
            if len(self._recent_events) > 20:
                self._recent_events = self._recent_events[-20:]

        await self._memory.maybe_store_event(self.guid, self.name, event)

    async def handle_event(self, event: GameEvent) -> AgentTrace | None:
        """Decide whether to invoke the LLM and execute the response."""
        if not self._should_invoke_llm(event):
            return None

        if not self._cost.check_rate_limit(self.guid):
            logger.debug("bot_agent.rate_limited", bot_guid=self.guid)
            return None

        model = self._cost.select_model(event.event_type)
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
        context_msg = build_context_message(
            snapshot=snapshot,
            recent_events=self._recent_events,
            memories=memories,
            triggering_event=triggering_text,
        )

        config = ProviderConfig(model=model, system_prompt=self._system_prompt)

        trace = AgentTrace(
            bot_guid=self.guid,
            bot_name=self.name,
            event_type=event.event_type.value,
            model=model,
        )

        start = time.monotonic()
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
                    self._cost.record_usage(model, trace.tokens_in, trace.tokens_out)
                elif response_event.type == ProviderEventType.ERROR:
                    logger.error(
                        "bot_agent.provider_error",
                        bot_guid=self.guid,
                        error=response_event.data.get("text", ""),
                    )

            trace.latency_ms = (time.monotonic() - start) * 1000
            self._profile.total_llm_calls += 1

            logger.info(
                "bot_agent.invocation_complete",
                bot_guid=self.guid,
                event_type=event.event_type.value,
                model=model,
                latency_ms=round(trace.latency_ms),
                tool_calls=trace.tool_calls,
            )

        except Exception as exc:
            trace.latency_ms = (time.monotonic() - start) * 1000
            logger.error(
                "bot_agent.invocation_failed",
                bot_guid=self.guid,
                error=str(exc),
            )

        return trace

    def _should_invoke_llm(self, event: GameEvent) -> bool:
        if event.event_type == EventType.CHAT_RECEIVED:
            return True
        if event.event_type == EventType.COMBAT_START:
            return True
        if event.event_type == EventType.BOT_DIED:
            return True
        if event.event_type == EventType.GROUP_INVITE:
            return True
        if event.event_type == EventType.IDLE_TICK:
            return True
        if event.event_type == EventType.ZONE_CHANGED:
            return True
        return False

    def _extract_player_name(self, event: GameEvent) -> str | None:
        if isinstance(event, ChatReceivedEvent):
            return event.sender_name
        return None


def _event_summary(event: GameEvent) -> str:
    """Convert a GameEvent to a human-readable one-line summary."""
    if isinstance(event, ChatReceivedEvent):
        return f'{event.sender_name} says ({event.channel}): "{event.message}"'
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
        case EventType.ZONE_CHANGED:
            return f"Entered {getattr(event, 'new_zone', 'unknown zone')}"
        case EventType.TARGET_CHANGED:
            return f"New target: {getattr(event, 'new_target', 'none')}"
        case EventType.STRATEGY_CHANGED:
            return f"Strategy changed to: {getattr(event, 'new_strategy', '?')}"
        case EventType.IDLE_TICK:
            return "Nothing particular is happening. You are idle."
        case _:
            return f"Event: {event.event_type.value}"
