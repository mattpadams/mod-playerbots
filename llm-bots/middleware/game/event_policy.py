"""Declarative per-event-type LLM invocation policy.

Replaces three scattered ad-hoc pieces:
  - ``BotAgent._should_invoke_llm`` if-chain (what events trigger an LLM call)
  - ``AgentSupervisor._pick_best_event`` priority dict
  - ``CostController._IMPORTANT_EVENTS`` set (which model tier to use)

Adding a new event type for M4-M7 means adding one entry here —
nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass

from game.events import EventType


@dataclass(frozen=True)
class EventPolicy:
    """Controls how the system responds to one event type.

    Attributes
    ----------
    priority:
        Lower is more important. Used by ``_pick_best_event`` to choose
        among simultaneous events for the same tick.
    invoke_llm:
        Whether to call the LLM at all for this event. False = event is
        recorded to the recent-events buffer but never triggers a call.
    model_tier:
        ``"important"`` → ``settings.model_important`` (e.g. Sonnet).
        ``"default"`` → ``settings.model_default`` (e.g. Haiku).
    needs_combat_context:
        True → ``CombatContextBuilder`` will be awaited before the LLM
        call to enrich the prompt with party / enemy info.
    cooldown_seconds:
        Minimum seconds between LLM calls for this event type per bot.
        0 = no cooldown (rate limiter is still the ceiling).
    """

    priority: int = 50
    invoke_llm: bool = True
    model_tier: str = "default"
    needs_combat_context: bool = False
    needs_party_context: bool = False
    cooldown_seconds: float = 0.0


# Single source of truth for all event behavior.
POLICY_REGISTRY: dict[EventType, EventPolicy] = {
    # Highest priority: always call LLM, always important model
    EventType.CHAT_RECEIVED: EventPolicy(
        priority=0, model_tier="important"
    ),
    # Admin-injected force-say — treat like top-priority chat
    EventType.ADMIN_FORCE_SAY: EventPolicy(
        priority=0, model_tier="important"
    ),
    EventType.GROUP_INVITE: EventPolicy(
        priority=1, model_tier="important"
    ),
    EventType.HEALTH_CRITICAL: EventPolicy(
        priority=2,
        model_tier="important",
        needs_combat_context=True,
        cooldown_seconds=30.0,
    ),
    # Mirrors HEALTH_CRITICAL. Slightly lower priority — mana-out is
    # urgent but rarely lethal on the same tick.
    EventType.MANA_CRITICAL: EventPolicy(
        priority=3,
        model_tier="important",
        needs_combat_context=True,
        cooldown_seconds=45.0,
    ),
    EventType.BOT_DIED: EventPolicy(
        priority=3, model_tier="important"
    ),
    EventType.COMBAT_START: EventPolicy(
        priority=4,
        model_tier="important",
        needs_combat_context=True,
    ),
    EventType.ZONE_CHANGED: EventPolicy(
        priority=5, model_tier="default"
    ),
    EventType.IDLE_TICK: EventPolicy(
        priority=6, model_tier="default"
    ),
    # Recorded but never triggers an LLM call — too noisy
    EventType.COMBAT_END: EventPolicy(priority=90, invoke_llm=False),
    EventType.BOT_REVIVED: EventPolicy(priority=91, invoke_llm=False),
    EventType.TARGET_CHANGED: EventPolicy(priority=92, invoke_llm=False),
    EventType.STRATEGY_CHANGED: EventPolicy(priority=93, invoke_llm=False),
    EventType.ACTION_CHANGED: EventPolicy(priority=94, invoke_llm=False),
    EventType.PLAYER_NEARBY: EventPolicy(priority=95, invoke_llm=False),
    EventType.STATE_SNAPSHOT: EventPolicy(priority=99, invoke_llm=False),
    # M4: Party coordination
    # Loot rolls are urgent — rolls time out, so no cooldown and important
    # model tier. Only the arbitrated winner actually gets an LLM call.
    EventType.LOOT_ROLL_STARTED: EventPolicy(
        priority=1,
        model_tier="important",
        needs_party_context=True,
    ),
    # Quest pickups fire on every item; LLM is invoked but the default
    # tier keeps cost sane. The broadcast tool call is a single-line
    # party message, so the call is cheap.
    EventType.PARTY_QUEST_PROGRESS: EventPolicy(
        priority=7,
        model_tier="default",
        needs_party_context=True,
        cooldown_seconds=5.0,
    ),
    # Vendor / craft events are handled by the coordinator directly,
    # never by the LLM. They exist for memory + trace visibility.
    EventType.VENDOR_NEARBY: EventPolicy(priority=96, invoke_llm=False),
    EventType.CRAFT_REQUESTED: EventPolicy(
        priority=8,
        model_tier="default",
        needs_party_context=True,
    ),
    # M5: Dungeon coordination
    # Entry gets a real LLM call so the bot can announce arrival in
    # character and acknowledge role. Exit is recorded only.
    EventType.DUNGEON_ENTERED: EventPolicy(
        priority=4,
        model_tier="important",
    ),
    EventType.DUNGEON_EXITED: EventPolicy(
        priority=90, invoke_llm=False
    ),
    # Boss encounters: engage + phase changes warrant a real call so the
    # leader (or anyone with role text) can react. Defeat is bookkeeping.
    EventType.BOSS_ENGAGED: EventPolicy(
        priority=2,
        model_tier="important",
        needs_combat_context=True,
        cooldown_seconds=5.0,
    ),
    EventType.BOSS_PHASE_CHANGED: EventPolicy(
        priority=3,
        model_tier="important",
        needs_combat_context=True,
        cooldown_seconds=5.0,
    ),
    EventType.BOSS_DEFEATED: EventPolicy(priority=91, invoke_llm=False),
    # A single member death mid-encounter — leader-only, cheaper than a
    # full wipe call. Cooldown prevents a spam if two members go down
    # back-to-back on the same tick.
    EventType.PARTY_MEMBER_DIED: EventPolicy(
        priority=3,
        model_tier="important",
        needs_party_context=True,
        cooldown_seconds=10.0,
    ),
    # Wipes only fire for the leader — important-tier call to get a
    # character-consistent "my fault, let's try this" response.
    EventType.PARTY_WIPE: EventPolicy(
        priority=2,
        model_tier="important",
        needs_party_context=True,
    ),
    # Adds arriving mid-fight — short cooldown so repeated waves don't
    # each trigger a separate call, but urgent enough to use the
    # important tier when it does fire.
    EventType.ADDS_SPAWNED: EventPolicy(
        priority=3,
        model_tier="important",
        needs_combat_context=True,
        cooldown_seconds=15.0,
    ),
}


# Safe default for any event not explicitly registered (e.g., future
# event types added by a module that hasn't updated the registry).
_FALLBACK_POLICY = EventPolicy(priority=99, invoke_llm=False)


def get_policy(event_type: EventType) -> EventPolicy:
    """Return the policy for an event type, or a safe no-op fallback."""
    return POLICY_REGISTRY.get(event_type, _FALLBACK_POLICY)
