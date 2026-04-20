"""Party coordination tools — M4 additions.

Five tools the LLM calls to act within a party:
  - broadcast_quest_progress: "/p ItemName cur/req" after a pickup
  - trade_item: offer an item to a specific party member
  - roll_need / roll_greed / roll_pass: decide an active loot roll

The arbitration itself runs in ``PartyCoordinator`` before the LLM
is invoked; the LLM only ever sees a roll if it was chosen as the
pre-arbitrated winner. It can still choose to pass to let a needier
party member win.
"""
from __future__ import annotations

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType
from providers.tool_adapter import tool

_MAX_CHAT_LEN = 100


def _truncate(s: str) -> str:
    return s if len(s) <= _MAX_CHAT_LEN else s[: _MAX_CHAT_LEN - 1] + "…"


def create_party_tools(executor: CommandExecutor) -> list:
    """Create party coordination tools, closing over the shared executor."""

    @tool(
        name="broadcast_quest_progress",
        description=(
            "Post a short party-chat line reporting your current progress "
            "on a shared collection objective. Use this after EVERY pickup "
            "of a quest item when you are in a party — low drop rates make "
            "each item noteworthy. Format: 'ItemName cur/req'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "item_name": {"type": "string"},
                "current": {"type": "integer"},
                "required": {"type": "integer"},
            },
            "required": ["bot_guid", "item_name", "current", "required"],
        },
    )
    async def broadcast_quest_progress(args):
        msg = _truncate(
            f"{args['item_name']} {int(args['current'])}/{int(args['required'])}"
        )
        await executor.execute(
            BotCommand(
                command_type=CommandType.PARTY_CHAT,
                bot_guid=args["bot_guid"],
                payload={"message": msg},
            )
        )
        return {"content": [{"type": "text", "text": f"Broadcast: {msg}"}]}

    @tool(
        name="trade_item",
        description=(
            "Initiate a trade with a party member and offer an item. Use "
            "to hand surplus quest-collection items to lagging party "
            "members, or to pass gear upgrades. The target must be a "
            "party member within trade range."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "target_player": {"type": "string"},
                "item_link": {"type": "string"},
                "count": {
                    "type": "integer",
                    "description": "Stack count; omit or 1 for a single item.",
                },
            },
            "required": ["bot_guid", "target_player", "item_link"],
        },
    )
    async def trade_item(args):
        await executor.execute(
            BotCommand(
                command_type=CommandType.TRADE_ITEM,
                bot_guid=args["bot_guid"],
                payload={
                    "target_player": args["target_player"],
                    "item_link": args["item_link"],
                    "count": args.get("count"),
                },
            )
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Trading {args['item_link']} to {args['target_player']}.",
                }
            ]
        }

    def _roll_tool(name: str, decision: str, desc: str):
        @tool(
            name=name,
            description=desc,
            input_schema={
                "type": "object",
                "properties": {
                    "bot_guid": {"type": "integer"},
                    "item_link": {"type": "string"},
                },
                "required": ["bot_guid", "item_link"],
            },
        )
        async def _roll(args):
            await executor.execute(
                BotCommand(
                    command_type=CommandType.LOOT_ROLL,
                    bot_guid=args["bot_guid"],
                    payload={
                        "decision": decision,
                        "item_link": args["item_link"],
                    },
                )
            )
            return {
                "content": [
                    {"type": "text", "text": f"Rolled {decision} on {args['item_link']}."}
                ]
            }

        return _roll

    roll_need = _roll_tool(
        "roll_need",
        "need",
        "Roll Need on the current loot item. Use only if the item is "
        "a genuine upgrade for you and no higher-priority party member "
        "would be better served by it.",
    )
    roll_greed = _roll_tool(
        "roll_greed",
        "greed",
        "Roll Greed on the current loot item. Use for side-grade or "
        "disenchant / vendor value.",
    )
    roll_pass = _roll_tool(
        "roll_pass",
        "pass",
        "Pass on the current loot item. Use to hand the upgrade to a "
        "needier party member who couldn't win the arbitration this tick.",
    )

    return [
        broadcast_quest_progress,
        trade_item,
        roll_need,
        roll_greed,
        roll_pass,
    ]
