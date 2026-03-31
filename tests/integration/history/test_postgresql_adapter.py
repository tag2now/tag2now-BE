"""Integration tests for the PostgreSQL history adapter.

These tests require a running PostgreSQL instance.
Run with: pytest tests/integration/history/ -v
"""

import pytest
import pytest_asyncio

from sqlalchemy import text

from history.models import RoomSnapshotRecord
from shared.database import init_database, close_database, get_session_factory


@pytest_asyncio.fixture
async def db_session():
    """Provide a session wrapped in a transaction that rolls back after each test."""
    await init_database()
    factory = get_session_factory()

    # Truncate tables before the test transaction to clear leftover data
    # async with factory() as cleanup_session:
    #     async with cleanup_session.begin():
    #         await cleanup_session.execute(text("TRUNCATE room_snapshots, room_snapshot_members, hourly_stats RESTART IDENTITY CASCADE"))

    async with factory() as session:
        async with session.begin():
            yield session
            await session.rollback()
    await close_database()


@pytest_asyncio.fixture
def adapter():
    from history.adapters.postgresql import PostgresHistoryAdapter
    return PostgresHistoryAdapter()


def _make_record(**overrides):
    defaults = dict(
        room_id=100, room_type="rank_match", owner_npid="p1",
        owner_online_name="P1", current_members=1, max_slots=2,
        is_matchmaking=False, member_npids=["p1"], member_online_names=["P1"],
    )
    defaults.update(overrides)
    return RoomSnapshotRecord(**defaults)


@pytest.mark.asyncio
async def test_record_snapshot_inserts_rows(adapter, db_session):
    records = [_make_record(), _make_record(room_id=101, owner_npid="p2", owner_online_name="P2", member_npids=["p2"], member_online_names=["P2"])]
    await adapter.record_snapshot(db_session, records)

    from history.entities import RoomSnapshotRow
    from sqlalchemy import select
    rows = (await db_session.execute(select(RoomSnapshotRow))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_record_snapshot_upserts_hourly_stats(adapter, db_session):
    records = [_make_record(current_members=3)]
    await adapter.record_snapshot(db_session, records)
    await adapter.record_snapshot(db_session, records)  # second call should upsert

    from history.entities import HourlyStatsRow
    from sqlalchemy import select
    rows = (await db_session.execute(select(HourlyStatsRow))).scalars().all()
    # There should be exactly one row for the current hour key
    from datetime import datetime, timedelta, timezone
    expected_key = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%dT%H")
    hour_keys = [r.hour_key for r in rows]
    assert hour_keys.count(expected_key) == 1


@pytest.mark.asyncio
async def test_record_snapshot_empty_list_noop(adapter, db_session):
    await adapter.record_snapshot(db_session, [])  # Should not raise


@pytest.mark.asyncio
async def test_get_hourly_activity_returns_24_hours(adapter, db_session):
    result = await adapter.get_hourly_activity(db_session, days=7)
    assert len(result) == 24
    assert all(h.hour == i for i, h in enumerate(result))


@pytest.mark.asyncio
async def test_get_player_stats_and_hours(adapter, db_session):
    records = [_make_record(owner_npid="test_player", member_npids=["test_player"], member_online_names=["TP"])]
    await adapter.record_snapshot(db_session, records)

    stats = await adapter.get_player_stats(db_session, "test_player", days=1)
    assert stats.npid == "test_player"
    assert stats.times_seen >= 1

    hours = await adapter.get_player_hours(db_session, "test_player", days=1)
    assert isinstance(hours, list)
