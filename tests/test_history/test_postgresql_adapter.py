"""Integration tests for the PostgreSQL history adapter.

These tests require a running PostgreSQL instance (docker-compose).
Run with: pytest -m integration
"""

import pytest
import pytest_asyncio

from history.models import RoomSnapshotRecord
from shared.database import init_database, get_session_factory

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(scope="module")
async def db_session_factory():
    """Create a test database engine and tables."""
    await init_database()
    return get_session_factory()


@pytest_asyncio.fixture
async def adapter(db_session_factory):
    from history.adapters.postgresql import PostgresHistoryAdapter
    a = PostgresHistoryAdapter(session_factory=db_session_factory)
    await a.init()
    yield a
    await a.close()


def _make_record(**overrides):
    defaults = dict(
        room_id=100, room_type="rank_match", owner_npid="p1",
        owner_online_name="P1", current_members=1, max_slots=2,
        is_matchmaking=False, member_npids=["p1"], member_online_names=["P1"],
    )
    defaults.update(overrides)
    return RoomSnapshotRecord(**defaults)


@pytest.mark.asyncio
async def test_record_snapshot_inserts_rows(adapter, db_session_factory):
    records = [_make_record(), _make_record(room_id=101, owner_npid="p2", owner_online_name="P2", member_npids=["p2"], member_online_names=["P2"])]
    await adapter.record_snapshot(records)

    from history.entities import RoomSnapshotRow
    from sqlalchemy import select
    async with db_session_factory() as session:
        rows = (await session.execute(select(RoomSnapshotRow))).scalars().all()
    assert len(rows) >= 2


@pytest.mark.asyncio
async def test_record_snapshot_upserts_hourly_stats(adapter, db_session_factory):
    records = [_make_record(current_members=3)]
    await adapter.record_snapshot(records)
    await adapter.record_snapshot(records)  # second call should upsert

    from history.entities import HourlyStatsRow
    from sqlalchemy import select
    async with db_session_factory() as session:
        rows = (await session.execute(select(HourlyStatsRow))).scalars().all()
    # There should be exactly one row for the current hour key
    hour_keys = [r.hour_key for r in rows]
    from history.adapters.postgresql import _kst_hour_key
    assert hour_keys.count(_kst_hour_key()) == 1


@pytest.mark.asyncio
async def test_record_snapshot_empty_list_noop(adapter):
    await adapter.record_snapshot([])  # Should not raise


@pytest.mark.asyncio
async def test_get_hourly_activity_returns_24_hours(adapter):
    result = await adapter.get_hourly_activity(days=7)
    assert len(result) == 24
    assert all(h.hour == i for i, h in enumerate(result))


@pytest.mark.asyncio
async def test_get_player_stats_and_hours(adapter):
    records = [_make_record(owner_npid="test_player", member_npids=["test_player"], member_online_names=["TP"])]
    await adapter.record_snapshot(records)

    stats = await adapter.get_player_stats("test_player", days=1)
    assert stats.npid == "test_player"
    assert stats.times_seen >= 1

    hours = await adapter.get_player_hours("test_player", days=1)
    assert isinstance(hours, list)
