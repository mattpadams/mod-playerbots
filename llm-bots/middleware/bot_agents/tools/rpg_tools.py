"""Proactive RPG behavior tools — M4.

These tools let an idle bot decide what to do next: change high-level
RPG status (grind / rest / etc.) and travel somewhere. The backing
C++ commands live in mod-playerbots: ``rpg mode <status>`` (new
``SetRpgModeAction``) and ``go`` (existing ``GoAction``).
"""
from __future__ import annotations

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType
from providers.tool_adapter import tool

_RPG_MODES = ["rest", "idle", "explore"]


def create_rpg_tools(executor: CommandExecutor) -> list:
    """Create proactive-behavior tools, closing over the shared executor."""

    @tool(
        name="set_rpg_mode",
        description=(
            "Change your proactive RPG behavior. 'rest' (sit and "
            "recover), 'idle' (stand around), 'explore' (wander the "
            "zone). For grinding use the 'grind' strategy via "
            "set_strategy; for questing use accept_quest / share_quest "
            "directly. Pick based on personality and current situation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "mode": {
                    "type": "string",
                    "enum": _RPG_MODES,
                },
            },
            "required": ["bot_guid", "mode"],
        },
    )
    async def set_rpg_mode(args):
        mode = args["mode"]
        await executor.execute(
            BotCommand(
                command_type=CommandType.SET_RPG_MODE,
                bot_guid=args["bot_guid"],
                payload={"mode": mode},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Switching to {mode} mode."}
            ]
        }

    @tool(
        name="go_to_location",
        description=(
            "Travel to a destination. Accepts a zone or stored-position "
            "name ('Darkshire', 'Stormwind'), a nearby unit or "
            "GameObject name, or three space-separated absolute map "
            "coordinates ('-8834.5 625.2 94.1'). Prefix with 'travel ' "
            "to use the zone travel system for named destinations."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "destination": {
                    "type": "string",
                    "description": (
                        "Zone / unit / object name, 'travel <name>', "
                        "or 'x y z' coordinates."
                    ),
                },
            },
            "required": ["bot_guid", "destination"],
        },
    )
    async def go_to_location(args):
        dest = args["destination"].strip()
        payload: dict = {}
        parts = dest.split()
        if len(parts) == 3:
            try:
                payload = {
                    "x": float(parts[0]),
                    "y": float(parts[1]),
                    "z": float(parts[2]),
                }
            except ValueError:
                payload = {"destination": dest}
        else:
            payload = {"destination": dest}
        await executor.execute(
            BotCommand(
                command_type=CommandType.GO_TO,
                bot_guid=args["bot_guid"],
                payload=payload,
            )
        )
        return {"content": [{"type": "text", "text": f"Heading to {dest}."}]}

    return [set_rpg_mode, go_to_location]
