import asyncio
from datetime import datetime, timedelta

import pytest

from chat.adapters.memory_repository import MemoryChatRepository
from chat.adapters.memory_bus import MemoryChatEventBus
from chat.domain import KST, Deleted, Posted
from chat.service import ChatService
from shared.exceptions import ForbiddenError, NotFoundError, RateLimitedError


class MovableClock:
    def __init__(self, now: datetime):
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta) -> None:
        self.current += timedelta(**delta)


@pytest.fixture
def clock():
    return MovableClock(datetime(2026, 10, 7, 21, 0, tzinfo=KST))


@pytest.fixture
def bus():
    return MemoryChatEventBus()


@pytest.fixture
def service(clock, bus):
    return ChatService(MemoryChatRepository(max_kept=10), bus, clock)


# Every read is bounded: an event that never comes would otherwise leave the
# test waiting on the queue forever instead of failing.
async def _next(subscription):
    return await asyncio.wait_for(_first(subscription), 1)


async def _first(subscription):
    async for event in subscription:
        return event


async def test_a_posted_message_is_stored_and_broadcast(service, bus):
    async with bus.subscribe() as events:
        message = await service.post_message(subject="alice", display_name="Alice", body="한 판 하실 분")

        assert await _next(events) == Posted(message)
    assert await service.recent_messages() == [message]
    assert (message.author_username, message.author_online_name, message.body) == ("alice", "Alice", "한 판 하실 분")


async def test_posting_again_within_a_second_is_refused(service, clock):
    await service.post_message(subject="alice", display_name="Alice", body="first")
    clock.advance(milliseconds=500)

    with pytest.raises(RateLimitedError):
        await service.post_message(subject="alice", display_name="Alice", body="second")

    assert [m.body for m in await service.recent_messages()] == ["first"]


async def test_the_interval_is_per_account_and_passes(service, clock):
    await service.post_message(subject="alice", display_name="Alice", body="a1")
    await service.post_message(subject="bob", display_name="Bob", body="b1")
    clock.advance(seconds=1)
    await service.post_message(subject="alice", display_name="Alice", body="a2")

    assert [m.body for m in await service.recent_messages()] == ["a1", "b1", "a2"]


async def test_the_previous_play_day_is_listed_but_nothing_older(service, clock):
    clock.current = datetime(2026, 10, 7, 5, 59, tzinfo=KST)
    await service.post_message(subject="alice", display_name="Alice", body="two nights ago")
    clock.current = datetime(2026, 10, 8, 5, 59, tzinfo=KST)
    await service.post_message(subject="alice", display_name="Alice", body="last night")
    clock.current = datetime(2026, 10, 8, 6, 0, tzinfo=KST)
    await service.post_message(subject="alice", display_name="Alice", body="this morning")

    assert [m.body for m in await service.recent_messages()] == ["last night", "this morning"]


async def test_the_author_deletes_their_own_message(service, bus):
    message = await service.post_message(subject="alice", display_name="Alice", body="oops")

    async with bus.subscribe() as events:
        await service.delete_message(message.id, subject="alice", admin=False)

        assert await _next(events) == Deleted(message.id)
    assert await service.recent_messages() == []


async def test_someone_else_cannot_delete_it(service):
    message = await service.post_message(subject="alice", display_name="Alice", body="mine")

    with pytest.raises(ForbiddenError):
        await service.delete_message(message.id, subject="bob", admin=False)

    assert await service.recent_messages() == [message]


async def test_an_admin_deletes_anyones_message(service):
    message = await service.post_message(subject="alice", display_name="Alice", body="spam")

    await service.delete_message(message.id, subject="moderator", admin=True)

    assert await service.recent_messages() == []


async def test_deleting_a_missing_message_is_not_found(service):
    with pytest.raises(NotFoundError):
        await service.delete_message(999, subject="alice", admin=True)


async def test_the_store_keeps_only_the_newest_messages(clock):
    service = ChatService(MemoryChatRepository(max_kept=2), MemoryChatEventBus(), clock)
    for body in ("one", "two", "three"):
        await service.post_message(subject=body, display_name=body, body=body)

    assert [m.body for m in await service.recent_messages()] == ["two", "three"]
