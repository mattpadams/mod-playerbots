"""Assembles the system prompt for a bot agent from personality + state + memories."""

from __future__ import annotations

from core.game_client import BotSnapshot
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


def build_context_message(
    snapshot: BotSnapshot,
    recent_events: list[str],
    memories: list[str],
    triggering_event: str,
) -> str:
    """Build the user-side context message for an LLM call."""
    sections = []

    # Current state
    sections.append(f"""[CURRENT STATE]
Location: {snapshot.zone} (x={snapshot.position_x:.0f}, y={snapshot.position_y:.0f})
Health: {snapshot.hp_pct}%
Status: {snapshot.state}
Target: {snapshot.target_name or 'none'}
Active strategy: {snapshot.strategy}""")

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
