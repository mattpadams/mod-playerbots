"""Vendor interaction tools — M4.

Player-to-player trading lives in ``party_tools.trade_item``; this
module covers vendor NPCs (buy / sell) which are non-party economic
actions. Split keeps the party toolkit tightly scoped to coordination.
"""
from __future__ import annotations

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType
from providers.tool_adapter import tool


def create_trade_tools(executor: CommandExecutor) -> list:
    """Create vendor-interaction tools, closing over the shared executor."""

    @tool(
        name="buy_from_vendor",
        description=(
            "Buy an item from the nearest vendor you are currently "
            "interacting with. Omit ``item_link`` to auto-purchase the "
            "set of useful items mod-playerbots considers vendor-worthy "
            "(pots, arrows, reagents)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "item_link": {
                    "type": "string",
                    "description": "Specific item link. Omit to auto-buy.",
                },
            },
            "required": ["bot_guid"],
        },
    )
    async def buy_from_vendor(args):
        link = args.get("item_link")
        await executor.execute(
            BotCommand(
                command_type=CommandType.VENDOR_BUY,
                bot_guid=args["bot_guid"],
                payload={"item_link": link} if link else {},
            )
        )
        target = link or "useful vendor items"
        return {"content": [{"type": "text", "text": f"Buying {target}."}]}

    @tool(
        name="sell_to_vendor",
        description=(
            "Sell items to the nearest vendor. ``filter`` = 'gray' "
            "(all grey trash, default), 'vendor' (all items flagged "
            "AH/vendor by the item-usage strategy), or a specific "
            "item link."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "filter": {
                    "type": "string",
                    "description": "'gray', 'vendor', or an item link.",
                },
            },
            "required": ["bot_guid"],
        },
    )
    async def sell_to_vendor(args):
        filt = args.get("filter", "gray")
        await executor.execute(
            BotCommand(
                command_type=CommandType.VENDOR_SELL,
                bot_guid=args["bot_guid"],
                payload={"filter": filt},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Selling {filt} to vendor."}
            ]
        }

    return [buy_from_vendor, sell_to_vendor]
