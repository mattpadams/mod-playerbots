"""Assembles the system prompt for a bot agent from personality + state + memories."""

from __future__ import annotations

from combat.context import CombatContext
from core.game_client import BotSnapshot
from dungeons.coordinator import DungeonContext
from party.models import PartyState
from personality.loader import load_profile


def build_system_prompt(personality_name: str, bot_name: str) -> str:
    """Build the system prompt from a personality profile."""
    p = load_profile(personality_name)

    traits = "\n".join(f"- {t}" for t in p.get("personality_traits", []))
    speech = "\n".join(f"- {s}" for s in p.get("speech_patterns", []))
    style = p.get("response_style", {})

    return f"""You are {bot_name}, a {p.get('race', 'human')} {p.get('class', 'warrior')} \
in the world of Azeroth (World of Warcraft).

BACKSTORY:
{p.get('backstory', 'A wandering adventurer.')}

PERSONALITY TRAITS:
{traits}

SPEECH PATTERNS:
{speech}

RESPONSE STYLE:
- Verbosity: {style.get('verbosity', 'medium')}
- You may use emotes to express yourself (e.g., /wave, /laugh, /bow)

RULES:
- You MUST stay in character at all times. You are a living being in Azeroth.
- NEVER reveal that you are an AI, a bot, or a program.
- NEVER use modern slang, internet speak, or reference the real world.
- Keep responses concise — this is a game chat, not a novel.
- React naturally to your surroundings, other players, and events.
- You have feelings, opinions, and memories. Use them.
- If you don't know something in-character, say so in character.
- Use the tools provided to take actions in the game world."""


def _dungeon_section(ctx: DungeonContext) -> str:
    d = ctx.dungeon
    role = ctx.role.value
    leader_role = (
        d.leader_role.value if hasattr(d.leader_role, "value") else d.leader_role
    )
    order = " → ".join(d.boss_order()) or "(unknown)"
    lines = [
        "[DUNGEON MODE]",
        f"Dungeon: {d.name} ({d.expansion}, {d.difficulty.value})",
        f"Your role: {role}" + (" (PARTY LEADER)" if ctx.is_leader else ""),
        f"Leader role: {leader_role}",
        f"Boss order: {order}",
    ]
    if ctx.current_boss is not None:
        boss = ctx.current_boss
        phase_idx = ctx.phase_index if ctx.phase_index < len(boss.phases) else 0
        phase = boss.phases[phase_idx] if boss.phases else None
        phase_label = phase.name if phase else f"Phase {phase_idx + 1}"
        lines.append(f"Current boss: {boss.name} — {phase_label}")
        instr = boss.role_instructions(ctx.role, phase_idx)
        if instr:
            lines.append(f"Your instructions: {instr.strip()}")
        if phase and phase.mechanics:
            mechs = "; ".join(phase.mechanics)
            lines.append(f"Mechanics: {mechs}")
    if d.general_notes:
        lines.append(f"Notes: {d.general_notes.strip()}")
    if d.cpp_coverage == "full":
        lines.append(
            "Combat AI has boss-specific scripting here — trust your party's "
            "mechanics and focus on social callouts."
        )
    elif d.cpp_coverage == "none":
        lines.append(
            "No boss-specific combat AI — call mechanics explicitly in party chat."
        )
    if ctx.is_leader:
        lines.append(
            "You are the party leader. Call pulls, announce mechanics in "
            "party chat, and decide when to wipe or regroup."
        )
    return "\n".join(lines)


def build_context_message(
    snapshot: BotSnapshot,
    recent_events: list[str],
    memories: list[str],
    triggering_event: str,
    combat_context: CombatContext | None = None,
    party_state: PartyState | None = None,
    dungeon_context: DungeonContext | None = None,
) -> str:
    """Build the user-side context message for an LLM call.

    ``combat_context`` is rendered as an additional ``[COMBAT SITUATION]``
    section when provided (typically only on combat-triggering events).

    ``party_state`` is rendered as a ``[PARTY STATE]`` section between
    current state and recent events whenever the bot is in a party.
    """
    sections = []

    # Current state — always cheap to render
    target_line = f"Target: {snapshot.target_name or 'none'}"
    if snapshot.target_hp_pct is not None:
        target_line += f" ({snapshot.target_hp_pct}% HP)"
    last_action_line = f"Last action: {snapshot.last_action or 'none'}"

    sections.append(f"""[CURRENT STATE]
Location: {snapshot.zone} (x={snapshot.position_x:.0f}, y={snapshot.position_y:.0f})
Health: {snapshot.hp_pct}%
Status: {snapshot.state}
{target_line}
{last_action_line}
Active strategy: {snapshot.strategy}""")

    # Dungeon enrichment — rendered whenever the bot is inside a known
    # instance, with or without a current boss resolved.
    if dungeon_context is not None:
        sections.append(_dungeon_section(dungeon_context))

    # Party enrichment — rendered whenever the bot is actually partied
    if party_state is not None and party_state.is_partied:
        section = party_state.to_prompt_section()
        if section:
            sections.append(section)

    # Combat enrichment — only when a combat event triggered the call
    if combat_context is not None:
        section = combat_context.to_prompt_section()
        if section:
            sections.append(section)

    # Recent events
    if recent_events:
        event_lines = "\n".join(f"- {e}" for e in recent_events[-10:])
        sections.append(f"[RECENT EVENTS]\n{event_lines}")

    # Relevant memories
    if memories:
        mem_lines = "\n".join(f"- {m}" for m in memories)
        sections.append(f"[RELEVANT MEMORIES]\n{mem_lines}")

    # Triggering event
    sections.append(f"[WHAT JUST HAPPENED]\n{triggering_event}")

    return "\n\n".join(sections)
