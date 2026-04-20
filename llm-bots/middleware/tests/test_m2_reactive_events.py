"""Milestone 2: Reactive Events tests.

Run with:
    cd llm-bots/middleware
    python -m pytest tests/test_m2_reactive_events.py -v

These tests verify:
1. The EventBus wake mechanism triggers immediately on publish.
2. The /events/chat HTTP endpoint creates the correct event and wakes
   the supervisor.
3. The supervisor exits its sleep early when a push event arrives.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.event_bus import EventBus
from game.events import ChatReceivedEvent


# ---------------------------------------------------------------------------
# EventBus wake tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wake_event_set_on_publish():
    """Publishing an event should set the wake flag."""
    bus = EventBus()
    assert not bus.wake_event.is_set()

    event = ChatReceivedEvent(
        bot_guid=100,
        bot_name="TestBot",
        sender_name="Player",
        message="hello",
        channel="whisper",
    )
    await bus.publish(event)
    assert bus.wake_event.is_set()


@pytest.mark.asyncio
async def test_clear_wake_resets_flag():
    """clear_wake should reset the flag so the next wait blocks."""
    bus = EventBus()
    event = ChatReceivedEvent(bot_guid=100, message="hi")
    await bus.publish(event)
    assert bus.wake_event.is_set()

    bus.clear_wake()
    assert not bus.wake_event.is_set()


@pytest.mark.asyncio
async def test_wake_event_unblocks_waiter():
    """A coroutine waiting on wake_event should unblock immediately
    when an event is published."""
    bus = EventBus()
    woke_up = False

    async def waiter():
        nonlocal woke_up
        await bus.wake_event.wait()
        woke_up = True

    task = asyncio.create_task(waiter())
    # Give waiter time to start waiting
    await asyncio.sleep(0.01)
    assert not woke_up

    event = ChatReceivedEvent(bot_guid=100, message="wake up")
    await bus.publish(event)
    await asyncio.sleep(0.01)
    assert woke_up

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_publish_drains_correctly():
    """Events published via push should be retrievable via drain."""
    bus = EventBus()
    e1 = ChatReceivedEvent(bot_guid=42, message="first")
    e2 = ChatReceivedEvent(bot_guid=42, message="second")
    await bus.publish(e1)
    await bus.publish(e2)

    events = bus.drain(42)
    assert len(events) == 2
    assert events[0].message == "first"
    assert events[1].message == "second"


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_endpoint_publishes_event():
    """The /events/chat endpoint should create a ChatReceivedEvent and
    publish it to the EventBus."""
    from api.events import ChatEventPayload, init, receive_chat_event

    bus = EventBus()
    init(bus)

    payload = ChatEventPayload(
        bot_guid=999,
        bot_name="Gandalf",
        sender_name="Frodo",
        message="You shall not pass!",
        channel="whisper",
    )
    result = await receive_chat_event(payload)

    assert result == {"status": "accepted"}
    assert bus.wake_event.is_set()

    events = bus.drain(999)
    assert len(events) == 1
    assert isinstance(events[0], ChatReceivedEvent)
    assert events[0].sender_name == "Frodo"
    assert events[0].message == "You shall not pass!"
    assert events[0].channel == "whisper"


# ---------------------------------------------------------------------------
# Supervisor early wake test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_supervisor_wakes_early_on_push():
    """The supervisor loop should exit its sleep early when a push
    event arrives, rather than waiting the full tick interval."""
    from bot_agents.agent_supervisor import AgentSupervisor

    bus = EventBus()
    supervisor = AgentSupervisor(
        game_client=MagicMock(),
        registry=MagicMock(all_elevated=MagicMock(return_value=[])),
        event_bus=bus,
        memory_manager=MagicMock(),
        cost_controller=MagicMock(),
        provider=MagicMock(),
        tick_interval=10.0,  # very long — we should NOT wait this long
    )

    loop_count = 0
    original_tick = supervisor._tick

    async def counting_tick():
        nonlocal loop_count
        loop_count += 1
        if loop_count >= 2:
            await supervisor.stop()

    supervisor._tick = counting_tick

    # Push an event after a short delay to wake the supervisor
    async def push_after_delay():
        await asyncio.sleep(0.1)
        event = ChatReceivedEvent(bot_guid=1, message="wake!")
        await bus.publish(event)

    start = time.monotonic()
    push_task = asyncio.create_task(push_after_delay())
    await supervisor.start()
    elapsed = time.monotonic() - start
    await push_task

    # Should complete in well under 10s (the tick interval)
    assert elapsed < 2.0, f"Supervisor took {elapsed:.1f}s — should wake early on push"
    assert loop_count >= 2
