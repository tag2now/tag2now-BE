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
async def test_record_snapshot_keeps_rooms_after_rpcn_counter_reset(adapter, db_session):
    """RPCN restarts reissue room ids from 1; those matches must still be stored."""
    await adapter.record_snapshot(db_session, [_make_record(room_id=5000, user1_npid="reset1", user2_npid="reset2")])
    await adapter.record_snapshot(db_session, [_make_record(room_id=1, user1_npid="reset3", user2_npid="reset4")])

    from history.entities import RankMatchSnapshotRow
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(RankMatchSnapshotRow).where(RankMatchSnapshotRow.user1_npid.in_(["reset1", "reset3"]))
    )).scalars().all()
    assert {r.room_id for r in rows} == {1, 5000}


@pytest.mark.asyncio
async def test_record_snapshot_deduplicates_reobserved_room(adapter, db_session):
    """A room still in progress after a backend restart must not be counted twice."""
    record = _make_record(room_id=7, user1_npid="dedup1", user2_npid="dedup2")
    await adapter.record_snapshot(db_session, [record])
    await adapter.record_snapshot(db_session, [record])

    from history.entities import RankMatchSnapshotRow
    from sqlalchemy import func, select
    count = (await db_session.execute(
        select(func.count()).select_from(RankMatchSnapshotRow).where(RankMatchSnapshotRow.user1_npid == "dedup1")
    )).scalar_one()
    assert count == 1


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
    # two dates under test inside this test transaction, on the same KST day
    # boundaries get_daily_summary groups by --- anchoring the delete to
    # yesterday_at instead would leave that day's earlier snapshots behind, and
    # their peak would outrank the one this test records.
    yesterday_start = datetime.combine(today - timedelta(days=1), time(), tzinfo=kst).astimezone(timezone.utc)
    tomorrow_start = datetime.combine(today + timedelta(days=1), time(), tzinfo=kst).astimezone(timezone.utc)
    await db_session.execute(delete(ActivitySnapshotRow).where(
        ActivitySnapshotRow.sampled_at >= yesterday_start,
        ActivitySnapshotRow.sampled_at < tomorrow_start,
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


@pytest.mark.asyncio
async def test_days_active_counts_kst_days_not_matches(adapter, db_session):
    """Three matches spread over two KST days are two active days, not three."""
    from datetime import datetime, timedelta, timezone
    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).replace(hour=21, minute=0, second=0, microsecond=0)
    await adapter.record_snapshot(db_session, [
        _make_record(room_id=9001, user1_npid="daycount", created_dt=today),
        _make_record(room_id=9002, user1_npid="daycount", created_dt=today + timedelta(minutes=20)),
        _make_record(room_id=9003, user1_npid="daycount", created_dt=today - timedelta(days=1)),
    ])

    stats = await adapter.get_player_stats(db_session, "daycount", days=7)
    assert stats.times_seen == 3
    assert stats.days_active == 2


@pytest.mark.asyncio
async def test_days_active_uses_kst_day_boundary(adapter, db_session):
    """01:00 and 23:00 KST on one day are one active day, though they straddle UTC midnight."""
    from datetime import datetime, timedelta, timezone
    KST = timezone(timedelta(hours=9))
    day = (datetime.now(KST) - timedelta(days=2)).replace(hour=1, minute=0, second=0, microsecond=0)
    await adapter.record_snapshot(db_session, [
        _make_record(room_id=9101, user1_npid="kstday", created_dt=day),
        _make_record(room_id=9102, user1_npid="kstday", created_dt=day + timedelta(hours=22)),
    ])

    stats = await adapter.get_player_stats(db_session, "kstday", days=7)
    assert stats.days_active == 1


@pytest.mark.asyncio
async def test_active_hours_requires_two_distinct_days(adapter, db_session):
    """A one-off session must not register as a habitual hour; two days at 21:00 must."""
    from datetime import datetime, timedelta, timezone
    KST = timezone(timedelta(hours=9))
    base = (datetime.now(KST) - timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
    await adapter.record_snapshot(db_session, [
        # 15:00 twice in one sitting --- one day only
        _make_record(room_id=9201, user1_npid="hours", created_dt=base.replace(hour=15)),
        _make_record(room_id=9202, user1_npid="hours", created_dt=base.replace(hour=15) + timedelta(minutes=10)),
        # 21:00 on two separate days
        _make_record(room_id=9203, user1_npid="hours", created_dt=base),
        _make_record(room_id=9204, user1_npid="hours", created_dt=base - timedelta(days=1)),
    ])

    stats = await adapter.get_player_stats(db_session, "hours", days=7)
    assert 21 in stats.active_hours
    assert 15 not in stats.active_hours
