import asyncio
from datetime import datetime, timezone

import pytest

from chat.adapters.memory_bus import MemoryChatEventBus
from chat.domain import Deleted, Message, Posted


def _posted(message_id: int) -> Posted:
    return Posted(Message(message_id, "alice", "Alice", "hi", datetime(2026, 10, 7, tzinfo=timezone.utc)))


async def _take(subscription, count: int) -> list:
    received = []
    async for event in subscription:
        received.append(event)
        if len(received) == count:
            break
    return received


async def _receive(subscription, count: int) -> list:
    return await asyncio.wait_for(_take(subscription, count), 1)


async def _nothing_arrives(subscription) -> bool:
    try:
        await asyncio.wait_for(_take(subscription, 1), 0.05)
    except TimeoutError:
        return True
    return False


async def test_every_subscriber_receives_each_event_in_order():
    bus = MemoryChatEventBus()

    async with bus.subscribe() as first, bus.subscribe() as second:
        await bus.publish(_posted(1))
        await bus.publish(Deleted(1))

        assert await _receive(first, 2) == [_posted(1), Deleted(1)]
        assert await _receive(second, 2) == [_posted(1), Deleted(1)]


async def test_a_late_subscriber_gets_only_what_is_published_after_it_joined():
    # What came before is the snapshot's job, not the bus's.
    bus = MemoryChatEventBus()

    async with bus.subscribe() as early:
        await bus.publish(_posted(1))
        async with bus.subscribe() as late:
            await bus.publish(_posted(2))

            assert await _receive(late, 1) == [_posted(2)]
            assert await _nothing_arrives(late)
        assert await _receive(early, 2) == [_posted(1), _posted(2)]


async def test_a_stream_that_has_closed_receives_nothing_more():
    bus = MemoryChatEventBus()

    async with bus.subscribe() as closed:
        pass
    await bus.publish(_posted(1))

    assert await _nothing_arrives(closed)


async def test_a_stream_that_ends_by_cancellation_is_unsubscribed_too():
    # The usual way a stream ends in production: the client goes away and
    # Starlette cancels the response, which raises inside the `with`.
    bus = MemoryChatEventBus()

    with pytest.raises(asyncio.CancelledError):
        async with bus.subscribe() as cancelled:
            raise asyncio.CancelledError
    await bus.publish(_posted(1))

    assert await _nothing_arrives(cancelled)


async def test_a_reader_whose_queue_is_exactly_full_still_receives_everything():
    bus = MemoryChatEventBus(queue_size=3)

    async with bus.subscribe() as slow:
        for message_id in (1, 2, 3):
            await bus.publish(_posted(message_id))

        assert await _receive(slow, 3) == [_posted(1), _posted(2), _posted(3)]


async def test_one_event_past_a_full_queue_drops_the_reader_and_ends_its_stream():
    bus = MemoryChatEventBus(queue_size=2)

    async with bus.subscribe() as stalled, bus.subscribe() as keeping_up:
        for message_id in (1, 2, 3):
            await bus.publish(_posted(message_id))
            assert await _receive(keeping_up, 1) == [_posted(message_id)]

        # The stalled stream ends rather than delivering a partial backlog; the
        # client reconnects and the snapshot replaces what it missed.
        assert await _receive(stalled, 99) == []

        await bus.publish(_posted(4))
        assert await _receive(keeping_up, 1) == [_posted(4)]
