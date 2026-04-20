"""HTTP push endpoint for game events (Milestone 2).

In Milestone 1 this is unused — events come from polling.
In Milestone 2 the C++ LlmBridgeHook POSTs events here for
low-latency chat response.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.event_bus import EventBus
from game.events import ChatReceivedEvent
from party.coordinator import PartyCoordinator

router = APIRouter(prefix="/events", tags=["events"])

_bus: EventBus | None = None
_party: PartyCoordinator | None = None


def init(event_bus: EventBus, party: PartyCoordinator | None = None) -> None:
    global _bus, _party
    _bus = event_bus
    _party = party


class ChatEventPayload(BaseModel):
    bot_guid: int
    bot_name: str = ""
    channel: str = "say"
    sender_name: str = ""
    message: str = ""


@router.post("/chat")
async def receive_chat_event(payload: ChatEventPayload):
    """Receive a chat event pushed from the C++ game server.

    This endpoint will be called by the LlmBridgeHook (Milestone 2)
    to immediately notify the agent of incoming chat, bypassing the
    poll cycle for faster response.
    """
    assert _bus is not None
    event = ChatReceivedEvent(
        bot_guid=payload.bot_guid,
        bot_name=payload.bot_name,
        channel=payload.channel,
        sender_name=payload.sender_name,
        message=payload.message,
    )
    await _bus.publish(event)
    return {"status": "accepted"}


class LootRollEventPayload(BaseModel):
    roll_id: str
    item_id: int
    item_link: str = ""
    item_name: str = ""
    candidate_guids: list[int] = []
    # Optional map guid -> score delta from mod-playerbots
    # StatsWeightCalculator. Absent means neutral 1.0 for everyone.
    item_scores: dict[int, float] | None = None


@router.post("/loot_roll")
async def receive_loot_roll_event(payload: LootRollEventPayload):
    """Receive a loot-roll-started event from the C++ LlmBridgeHook.

    The coordinator runs synchronous arbitration, sends ``roll pass``
    to the losers, and queues a ``LootRollStartedEvent`` for the
    winner so the next supervisor tick wakes the bot's agent.
    """
    if _party is None:
        return {"status": "disabled"}
    await _party.on_loot_roll_started(
        roll_id=payload.roll_id,
        item_id=payload.item_id,
        item_link=payload.item_link,
        item_name=payload.item_name,
        candidate_guids=payload.candidate_guids,
        item_scores=payload.item_scores,
    )
    # Wake the supervisor loop so the winner event is drained this tick.
    if _bus is not None:
        _bus.wake_event.set()
    return {"status": "accepted"}
