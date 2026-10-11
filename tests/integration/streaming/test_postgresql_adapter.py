"""PostgreSQL stream channel tests. Requires the test compose stack to be running."""

import pytest
import pytest_asyncio
from sqlalchemy import delete

from shared.database import close_database, get_session_factory, init_database
from streaming.entities import StreamChannelRow
from streaming.exceptions import ChannelTakenError
from streaming.models import PlatformChannel

ALICE_CH = "a" * 32
BOB_CH = "b" * 32


@pytest_asyncio.fixture
async def repo():
    from streaming.adapters.postgresql import PostgresStreamChannelRepository

    await init_database()
    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(StreamChannelRow))
    yield PostgresStreamChannelRepository()
    await close_database()


async def _run(work):
    async with get_session_factory()() as session, session.begin():
        return await work(session)


async def test_upsert_replaces_the_accounts_channel(repo):
    await _run(lambda s: repo.upsert(s, "alice", "chzzk", PlatformChannel(ALICE_CH, "처음")))
    await _run(lambda s: repo.upsert(s, "alice", "chzzk", PlatformChannel(BOB_CH, "바꾼 채널")))

    channel = await _run(lambda s: repo.get(s, "alice", "chzzk"))
    assert (channel.channel_id, channel.channel_name) == (BOB_CH, "바꾼 채널")
    assert [c.username for c in await _run(repo.list_all)] == ["alice"]


async def test_a_channel_held_by_another_account_is_taken(repo):
    await _run(lambda s: repo.upsert(s, "alice", "chzzk", PlatformChannel(ALICE_CH, "앨리스")))

    with pytest.raises(ChannelTakenError):
        await _run(lambda s: repo.upsert(s, "mallory", "chzzk", PlatformChannel(ALICE_CH, "앨리스")))

    assert await _run(lambda s: repo.get(s, "mallory", "chzzk")) is None


async def test_delete_matches_the_username_regardless_of_case(repo):
    await _run(lambda s: repo.upsert(s, "Alice", "chzzk", PlatformChannel(ALICE_CH, "앨리스")))

    assert await _run(lambda s: repo.delete(s, "alice", "chzzk")) is True
    assert await _run(lambda s: repo.delete(s, "alice", "chzzk")) is False
    assert await _run(repo.list_all) == []
