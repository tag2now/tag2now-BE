"""PostgreSQL chat tests. Requires the test compose stack to be running."""

from datetime import datetime, timedelta

import pytest_asyncio
from sqlalchemy import delete

from chat.adapters.memory_bus import MemoryChatEventBus
from chat.adapters.postgresql import PostgresChatRepository
from chat.domain import KST, MAX_LISTED_MESSAGES
from chat.entities import ChatMessageRow
from chat.service import ChatService
from shared.database import close_database, get_session_factory, init_database

NOON = datetime(2026, 10, 7, 12, 0, tzinfo=KST)


@pytest_asyncio.fixture
async def database():
    await init_database()
    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(ChatMessageRow))
    yield
    await close_database()


def _repo(max_listed: int = MAX_LISTED_MESSAGES) -> PostgresChatRepository:
    return PostgresChatRepository(get_session_factory(), max_listed)


async def _restart() -> None:
    await close_database()
    await init_database()


async def test_an_appended_message_is_listed_as_written(database):
    repo = _repo()

    message = await repo.append("alice", "Alice", "한 판 하실 분", NOON, author_admin=True)

    assert await repo.list_since(NOON) == [message]
    assert (
        message.author_username,
        message.author_online_name,
        message.body,
        message.created_at,
        message.author_admin,
    ) == (
        "alice",
        "Alice",
        "한 판 하실 분",
        NOON,
        True,
    )


async def test_list_since_starts_at_the_boundary_oldest_first(database):
    repo = _repo()
    await repo.append("alice", "Alice", "before", NOON - timedelta(seconds=1))
    at = await repo.append("bob", "Bob", "at", NOON)
    after = await repo.append("carol", "Carol", "after", NOON + timedelta(minutes=1))

    assert await repo.list_since(NOON) == [at, after]


async def test_list_since_keeps_only_the_newest(database):
    repo = _repo(max_listed=2)
    for minute in range(3):
        await repo.append("alice", "Alice", f"line {minute}", NOON + timedelta(minutes=minute))

    assert [m.body for m in await repo.list_since(NOON)] == ["line 1", "line 2"]


async def test_a_deleted_message_is_gone(database):
    repo = _repo()
    kept = await repo.append("alice", "Alice", "kept", NOON)
    gone = await repo.append("bob", "Bob", "gone", NOON)

    await repo.delete(gone.id)

    assert await repo.get(gone.id) is None
    assert await repo.get(kept.id) == kept
    assert await repo.list_since(NOON) == [kept]


async def test_chat_and_its_deletions_survive_a_restart(database):
    service = ChatService(_repo(), MemoryChatEventBus())
    kept = await service.post_message(subject="alice", display_name="Alice", body="kept")
    gone = await service.post_message(subject="bob", display_name="Bob", body="gone")
    await service.delete_message(gone.id, subject="bob", admin=False)

    await _restart()
    service = ChatService(_repo(), MemoryChatEventBus())

    assert await service.recent_messages() == [kept]
    later = await service.post_message(subject="carol", display_name="Carol", body="after the restart")
    assert later.id > gone.id
