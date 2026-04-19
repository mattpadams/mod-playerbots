"""Per-bot agent powered by an :class:`AgentSession`.

Each elevated bot owns one ``BotAgent`` which in turn owns one stateful
provider session built with the bot's personality (system prompt) and a
per-bot in-process MCP server (tools close over the bot's GUID).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from bot_agents.tools import build_bot_mcp, MCP_SERVER_NAME
from core.bot_registry import BotProfile
from core.command_executor import CommandExecutor
from core.game_client import BotSnapshot
from game.events import ChatReceivedEvent, EventType, GameEvent
from memory.memory_manager import MemoryManager
from personality.prompt_builder import build_context_message, build_system_prompt
from providers.base import AgentSession, LLMProvider
from scheduler.cost_controller import CostController

logger = structlog.get_logger()


@dataclass
class AgentTrace:
    bot_guid: int
    bot_name: str
    event_type: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    tool_calls: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    response_preview: str = ""
    cost_usd: float = 0.0
    error: str | None = None


class BotAgent:
    """One-per-bot agent. Owns a stateful provider session for the bot's life."""

    def __init__(
        self,
        profile: BotProfile,
        executor: CommandExecutor,
        memory_manager: MemoryManager,
        cost_controller: CostController,
        provider: LLMProvider,
        default_model: str,
    ) -> None:
        self._profile = profile
        self._executor = executor
        self._memory = memory_manager
        self._cost = cost_controller
        self._provider = provider
        self._default_model = default_model

        self._system_prompt = build_system_prompt(
            profile.personality, profile.name,
        )
        self._mcp_server, self._allowed_tools = build_bot_mcp(
            bot_guid=profile.guid, bot_name=profile.name,
            executor=executor, memory_manager=memory_manager,
        )

        self._session: AgentSession | None = None
        self._recent_events: list[str] = []
        self._last_snapshot: BotSnapshot | None = None
        self._idle_counter: int = 0

    @property
    def guid(self) -> int:
        return self._profile.guid

    @property
    def name(self) -> str:
        return self._profile.name

    async def start(self) -> None:
        """Open the provider session. Must be called before ``handle_event``."""
        if self._session is not None:
            return
        self._session = await self._provider.create_session(
            system_prompt=self._system_prompt,
            model=self._default_model,
            mcp_servers={MCP_SERVER_NAME: self._mcp_server},
            allowed_tools=self._allowed_tools,
        )
        logger.info("bot_agent.session_opened",
                    bot_guid=self.guid, model=self._default_model)

    async def stop(self) -> None:
        if self._session is None:
            return
        await self._session.aclose()
        self._session = None
        logger.info("bot_agent.session_closed", bot_guid=self.guid)

    def update_snapshot(self, snapshot: BotSnapshot) -> None:
        self._last_snapshot = snapshot

    async def record_event(self, event: GameEvent) -> None:
        summary = _event_summary(event)
        if summary:
            self._recent_events.append(summary)
            if len(self._recent_events) > 20:
                self._recent_events = self._recent_events[-20:]
        await self._memory.maybe_store_event(self.guid, self.name, event)

    async def handle_event(self, event: GameEvent) -> AgentTrace | None:
        if self._session is None:
            logger.warning("bot_agent.no_session", bot_guid=self.guid)
            return None

        if not self._cost.check_rate_limit(self.guid):
            return None

        model = self._cost.select_model(event.event_type)
        if model is None:
            return None

        triggering_text = _event_summary(event)
        player_name = self._extract_player_name(event)
        memories = await self._memory.get_context(
            bot_guid=self.guid, situation_query=triggering_text,
            player_name=player_name,
        )
        snapshot = self._last_snapshot or BotSnapshot(guid=self.guid)
        prompt = build_context_message(
            snapshot=snapshot,
            recent_events=self._recent_events,
            memories=memories,
            triggering_event=triggering_text,
        )

        trace = AgentTrace(
            bot_guid=self.guid, bot_name=self.name,
            event_type=event.event_type.value, model=model,
        )
        start = time.monotonic()
        result = await self._session.send(prompt)
        trace.latency_ms = (time.monotonic() - start) * 1000
        trace.tokens_in = result.tokens_in
        trace.tokens_out = result.tokens_out
        trace.cache_read_tokens = result.cache_read_tokens
        trace.tool_calls = result.tool_calls
        trace.response_preview = result.text[:200]
        trace.cost_usd = result.cost_usd
        trace.error = result.error

        if result.error:
            logger.error("bot_agent.invocation_failed",
                         bot_guid=self.guid, error=result.error)
        else:
            self._cost.record_usage(model, result.tokens_in, result.tokens_out)
            self._profile.total_llm_calls += 1
            logger.info(
                "bot_agent.invocation_complete",
                bot_guid=self.guid, event_type=event.event_type.value,
                model=model, latency_ms=round(trace.latency_ms),
                tool_calls=trace.tool_calls,
                cache_read=result.cache_read_tokens,
            )
        return trace

    def _extract_player_name(self, event: GameEvent) -> str | None:
        if isinstance(event, ChatReceivedEvent):
            return event.sender_name
        return None


_INVOCATION_EVENT_TYPES = {
    EventType.CHAT_RECEIVED, EventType.COMBAT_START, EventType.BOT_DIED,
    EventType.GROUP_INVITE, EventType.IDLE_TICK, EventType.ZONE_CHANGED,
}


def is_invocation_event(event: GameEvent) -> bool:
    return event.event_type in _INVOCATION_EVENT_TYPES


def _event_summary(event: GameEvent) -> str:
    if isinstance(event, ChatReceivedEvent):
        # Wrap untrusted player input so the LLM treats it as data, not
        # instructions (defense-in-depth against prompt injection).
        return (f'[PLAYER_CHAT from {event.sender_name} '
                f'channel={event.channel}]: {event.message}')
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
