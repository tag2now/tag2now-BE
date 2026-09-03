"""Integration tests for the PostgreSQL history adapter.

These tests require a running PostgreSQL instance.
Run with: pytest tests/integration/history/ -v
"""

import pytest
import pytest_asyncio

from history.models import RankMatchSnapshotRecord
from shared.database import init_database, close_database, get_session_factory


@pytest_asyncio.fixture
async def db_session():
    """Provide a session wrapped in a transaction that rolls back after each test."""
    await init_database()
    factory = get_session_factory()

    async with factory() as session:
        transaction = await session.begin()
        yield session
        await transaction.rollback()
    await close_database()


@pytest_asyncio.fixture
def adapter():
    from history.adapters.postgresql import PostgresHistoryAdapter
    return PostgresHistoryAdapter()


def _make_record(**overrides):
    from datetime import datetime, timedelta, timezone
    KST = timezone(timedelta(hours=9))
    defaults = dict(
        room_id=100, rank_id=10,
        user1_npid="p1", user1_online_name="P1",
        user2_npid="p2", user2_online_name="P2",
        created_dt=datetime.now(KST),
    )
    defaults.update(overrides)
    return RankMatchSnapshotRecord(**defaults)


@pytest.mark.asyncio
async def test_record_snapshot_inserts_rows(adapter, db_session):
    records = [_make_record(), _make_record(room_id=101, user1_npid="p3", user2_npid="p4")]
    await adapter.record_snapshot(db_session, records)

    from history.entities import RankMatchSnapshotRow
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(RankMatchSnapshotRow).where(RankMatchSnapshotRow.room_id.in_([100, 101]))
    )).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_record_snapshot_upserts_hourly_stats(adapter, db_session):
    records = [_make_record()]
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
async def test_record_daily_matched_players_deduplicates_per_kst_day(adapter, db_session):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from history.entities import DailyMatchedPlayerRow

    observed_at = datetime.now(timezone.utc)
    await adapter.record_daily_matched_players(db_session, {"p1", "p2"}, observed_at)
    await adapter.record_daily_matched_players(db_session, {"p1"}, observed_at)

    observed_date = (observed_at + timedelta(hours=9)).date()
    rows = (await db_session.execute(
        select(DailyMatchedPlayerRow).where(
            DailyMatchedPlayerRow.date == observed_date,
            DailyMatchedPlayerRow.npid.in_(["p1", "p2"]),
        )
    )).scalars().all()
    assert {(row.date, row.npid) for row in rows} == {
        (observed_date, "p1"),
        (observed_date, "p2"),
    }


@pytest.mark.asyncio
async def test_daily_matched_players_use_kst_calendar_days(adapter, db_session):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from history.entities import DailyMatchedPlayerRow

    await adapter.record_daily_matched_players(
        db_session, {"kst-boundary"}, datetime(2026, 1, 1, 14, 59, tzinfo=timezone.utc)
    )
    await adapter.record_daily_matched_players(
        db_session, {"kst-boundary"}, datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
    )

    rows = (await db_session.execute(
        select(DailyMatchedPlayerRow.date).where(DailyMatchedPlayerRow.npid == "kst-boundary")
    )).scalars().all()
    assert set(rows) == {datetime(2026, 1, 1).date(), datetime(2026, 1, 2).date()}


@pytest.mark.asyncio
async def test_daily_summary_counts_unique_players_in_requested_kst_days(adapter, db_session):
    from sqlalchemy import delete
    from history.entities import ActivitySnapshotRow, DailyMatchedPlayerRow
    from history.models import ActivitySnapshot
    from datetime import datetime, time, timedelta, timezone

    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    today_at = datetime.combine(today, time(12), tzinfo=kst).astimezone(timezone.utc)
    yesterday_at = today_at - timedelta(days=1)
    today_players = {"summary-today-a", "summary-today-b"}
    yesterday_players = {"summary-yesterday"}

    # The local integration DB may contain retained collector data.  Isolate the
    # two dates under test inside this test transaction.
    await db_session.execute(delete(ActivitySnapshotRow).where(
        ActivitySnapshotRow.sampled_at >= yesterday_at,
        ActivitySnapshotRow.sampled_at < today_at + timedelta(days=1),
    ))
    await db_session.execute(delete(DailyMatchedPlayerRow).where(
        DailyMatchedPlayerRow.date.in_([today, today - timedelta(days=1)]),
    ))
    await adapter.record_daily_matched_players(db_session, today_players, today_at)
    await adapter.record_daily_matched_players(db_session, yesterday_players, yesterday_at)
    await adapter.record_daily_matched_players(db_session, {"summary-today-a"}, today_at)
    await adapter.record_activity_snapshot(db_session, ActivitySnapshot(today_at, 5, 2, 3, 1))
    await adapter.record_activity_snapshot(db_session, ActivitySnapshot(today_at + timedelta(minutes=30), 9, 4, 6, 2))
    await adapter.record_activity_snapshot(db_session, ActivitySnapshot(yesterday_at, 3, 1, 2, 1))

    summary = await adapter.get_daily_summary(db_session, days=2)
    by_date = {row.date: row for row in summary}

    assert [row.date for row in summary] == sorted(row.date for row in summary)
    assert by_date[today.isoformat()].unique_players == 2
    assert by_date[(today - timedelta(days=1)).isoformat()].unique_players == 1
    assert by_date[today.isoformat()].peak_players == 9
    assert by_date[today.isoformat()].avg_players == 7.0
    assert by_date[today.isoformat()].peak_rooms == 4
    assert by_date[(today - timedelta(days=1)).isoformat()].peak_players == 3
    assert [row.date for row in await adapter.get_daily_summary(db_session, days=1)] == [today.isoformat()]


@pytest.mark.asyncio
async def test_daily_peak_snapshots_use_kst_calendar_days(adapter, db_session):
    from datetime import datetime, time, timedelta, timezone
    from sqlalchemy import delete
    from history.entities import ActivitySnapshotRow
    from history.models import ActivitySnapshot

    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    today_start = datetime.combine(today, time.min, tzinfo=kst).astimezone(timezone.utc)
    yesterday = today - timedelta(days=1)

    await db_session.execute(delete(ActivitySnapshotRow).where(
        ActivitySnapshotRow.sampled_at >= today_start - timedelta(days=1),
        ActivitySnapshotRow.sampled_at < today_start + timedelta(days=1),
    ))
    await adapter.record_activity_snapshot(db_session, ActivitySnapshot(
        today_start - timedelta(minutes=1), 11, 3, 2, 1,
    ))
    await adapter.record_activity_snapshot(db_session, ActivitySnapshot(
        today_start, 29, 8, 4, 2,
    ))

    by_date = {row.date: row for row in await adapter.get_daily_summary(db_session, days=2)}

    assert by_date[yesterday.isoformat()].peak_players == 11
    assert by_date[today.isoformat()].peak_players == 29


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
    records = [_make_record(user1_npid="test_player", user1_online_name="TP")]
    await adapter.record_snapshot(db_session, records)

    stats = await adapter.get_player_stats(db_session, "test_player", days=1)
    assert stats.npid == "test_player"
    assert stats.times_seen >= 1
    assert isinstance(stats.active_hours, list)
