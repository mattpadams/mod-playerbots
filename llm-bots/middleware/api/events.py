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

router = APIRouter(prefix="/events", tags=["events"])

_bus: EventBus | None = None


def init(event_bus: EventBus) -> None:
    global _bus
    _bus = event_bus


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
