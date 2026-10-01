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
    records = [
        _make_record(user1_npid="insert1", user2_npid="insert2"),
        _make_record(room_id=101, user1_npid="insert3", user2_npid="insert4"),
    ]
    await adapter.record_snapshot(db_session, records)

    # By npid, not room_id: RPCN hands out small room ids too, so a collected
    # match can share one with this test.
    from history.entities import RankMatchSnapshotRow
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(RankMatchSnapshotRow).where(RankMatchSnapshotRow.user1_npid.in_(["insert1", "insert3"]))
    )).scalars().all()
    assert {r.room_id for r in rows} == {100, 101}


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
async def test_record_daily_matched_players_deduplicates_per_stat_day(adapter, db_session):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from history.adapters.postgresql import stat_day
    from history.entities import DailyMatchedPlayerRow

    observed_at = datetime.now(timezone.utc)
    await adapter.record_daily_matched_players(db_session, {"p1", "p2"}, observed_at)
    await adapter.record_daily_matched_players(db_session, {"p1"}, observed_at)

    observed_date = stat_day(observed_at)
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
async def test_daily_matched_players_roll_over_at_six_kst(adapter, db_session):
    """05:59 KST still belongs to the previous day; 06:00 starts the new one."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from history.entities import DailyMatchedPlayerRow

    # 2026-01-02 05:59 KST and 06:00 KST, expressed in UTC (KST = UTC+9).
    await adapter.record_daily_matched_players(
        db_session, {"stat-day-boundary"}, datetime(2026, 1, 1, 20, 59, tzinfo=timezone.utc)
    )
    await adapter.record_daily_matched_players(
        db_session, {"stat-day-boundary"}, datetime(2026, 1, 1, 21, 0, tzinfo=timezone.utc)
    )

    rows = (await db_session.execute(
        select(DailyMatchedPlayerRow.date).where(DailyMatchedPlayerRow.npid == "stat-day-boundary")
    )).scalars().all()
    assert set(rows) == {datetime(2026, 1, 1).date(), datetime(2026, 1, 2).date()}


@pytest.mark.asyncio
async def test_daily_summary_counts_unique_players_in_requested_stat_days(adapter, db_session):
    from sqlalchemy import delete
    from history.adapters.postgresql import stat_day, stat_day_start
    from history.entities import ActivitySnapshotRow, DailyMatchedPlayerRow
    from history.models import ActivitySnapshot
    from datetime import datetime, timedelta, timezone

    today = stat_day(datetime.now(timezone.utc))
    # Noon of the statistics day --- safely inside it whichever hour it is now.
    today_at = stat_day_start(today) + timedelta(hours=12)
    yesterday_at = today_at - timedelta(days=1)
    today_players = {"summary-today-a", "summary-today-b"}
    yesterday_players = {"summary-yesterday"}

    # The local integration DB may contain retained collector data.  Isolate the
    # two dates under test inside this test transaction, on the same KST day
    # boundaries get_daily_summary groups by --- anchoring the delete to
    # yesterday_at instead would leave that day's earlier snapshots behind, and
    # their peak would outrank the one this test records.
    yesterday_start = stat_day_start(today - timedelta(days=1))
    tomorrow_start = stat_day_start(today + timedelta(days=1))
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
async def test_daily_peak_snapshots_split_at_the_stat_day_start(adapter, db_session):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete
    from history.adapters.postgresql import stat_day, stat_day_start
    from history.entities import ActivitySnapshotRow
    from history.models import ActivitySnapshot

    today = stat_day(datetime.now(timezone.utc))
    today_start = stat_day_start(today)
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
async def test_get_hourly_activity_returns_24_hours_from_the_stat_day_start(adapter, db_session):
    result = await adapter.get_hourly_activity(db_session, days=7)
    assert [h.hour for h in result] == list(range(6, 24)) + list(range(6))


@pytest.mark.asyncio
async def test_get_hourly_activity_averages_every_sample_in_the_kst_hour(adapter, db_session):
    """An idle sample still counts toward its hour, and hours are read on the KST clock."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete
    from history.entities import ActivitySnapshotRow
    from history.models import ActivitySnapshot
    KST = timezone(timedelta(hours=9))

    # 03:00 KST two days ago --- well inside a 7-day window whatever the time now.
    three_am = (datetime.now(KST) - timedelta(days=2)).replace(hour=3, minute=0, second=0, microsecond=0)
    day_before = three_am - timedelta(days=1)
    await db_session.execute(delete(ActivitySnapshotRow).where(
        ActivitySnapshotRow.sampled_at >= three_am - timedelta(days=9),
    ))
    for sampled_at, players in [
        (day_before + timedelta(minutes=10), 0),
        (day_before + timedelta(minutes=40), 4),
        (three_am + timedelta(minutes=20), 8),
        (three_am + timedelta(hours=1), 20),
        (three_am - timedelta(days=8), 99),  # outside the 7-day window
    ]:
        await adapter.record_activity_snapshot(db_session, ActivitySnapshot(sampled_at, players, 0, 0, 0))

    by_hour = {h.hour: h for h in await adapter.get_hourly_activity(db_session, days=7)}

    assert (by_hour[3].avg_players, by_hour[3].peak_players) == (4.0, 8)
    assert (by_hour[4].avg_players, by_hour[4].peak_players) == (20.0, 20)
    assert (by_hour[5].avg_players, by_hour[5].peak_players) == (0, 0)


@pytest.mark.asyncio
async def test_hourly_peak_matches_the_daily_peak_over_the_same_samples(adapter, db_session):
    """Both charts read the same samples, so the busiest moment is one number on each."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete
    from history.adapters.postgresql import stat_day, stat_day_start
    from history.entities import ActivitySnapshotRow, DailyMatchedPlayerRow
    from history.models import ActivitySnapshot

    today = stat_day(datetime.now(timezone.utc))
    # A retained participant row with no snapshot beside it would add a day
    # whose peak is None to the daily summary.
    await db_session.execute(delete(ActivitySnapshotRow).where(
        ActivitySnapshotRow.sampled_at >= stat_day_start(today - timedelta(days=7)),
    ))
    await db_session.execute(delete(DailyMatchedPlayerRow).where(
        DailyMatchedPlayerRow.date >= today - timedelta(days=7),
    ))
    two_days_ago = stat_day_start(today - timedelta(days=2))
    for sampled_at, players in [
        (two_days_ago + timedelta(hours=6), 17),
        (two_days_ago + timedelta(hours=15), 35),
        (two_days_ago + timedelta(hours=15, minutes=30), 6),
    ]:
        await adapter.record_activity_snapshot(db_session, ActivitySnapshot(sampled_at, players, 0, 0, 0))

    hourly = await adapter.get_hourly_activity(db_session, days=7)
    daily = await adapter.get_daily_summary(db_session, days=7)

    assert max(h.peak_players for h in hourly) == max(d.peak_players for d in daily) == 35


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
async def test_days_active_keeps_one_late_night_session_on_one_day(adapter, db_session):
    """22:00 and 02:00 KST are one sitting, so they count as a single active day."""
    from datetime import datetime, timedelta, timezone
    KST = timezone(timedelta(hours=9))
    evening = (datetime.now(KST) - timedelta(days=2)).replace(hour=22, minute=0, second=0, microsecond=0)
    await adapter.record_snapshot(db_session, [
        _make_record(room_id=9101, user1_npid="statday", created_dt=evening),
        _make_record(room_id=9102, user1_npid="statday", created_dt=evening + timedelta(hours=4)),
    ])

    stats = await adapter.get_player_stats(db_session, "statday", days=7)
    assert stats.times_seen == 2
    assert stats.days_active == 1


@pytest.mark.asyncio
async def test_days_active_separates_sittings_across_the_six_kst_boundary(adapter, db_session):
    """05:59 and 06:00 KST fall on different statistics days."""
    from datetime import datetime, timedelta, timezone
    KST = timezone(timedelta(hours=9))
    dawn = (datetime.now(KST) - timedelta(days=2)).replace(hour=5, minute=59, second=0, microsecond=0)
    await adapter.record_snapshot(db_session, [
        _make_record(room_id=9111, user1_npid="statboundary", created_dt=dawn),
        _make_record(room_id=9112, user1_npid="statboundary", created_dt=dawn + timedelta(minutes=1)),
    ])

    stats = await adapter.get_player_stats(db_session, "statboundary", days=7)
    assert stats.times_seen == 2
    assert stats.days_active == 2


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


async def _record_weekly_matches(adapter, db_session):
    """Two test accounts sparring 100 times, and a regular with 90 matches."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=9)))
    spar = [
        _make_record(room_id=9300 + i, user1_npid="tester_a", user2_npid="tester_b", created_dt=now - timedelta(minutes=i))
        for i in range(100)
    ]
    regular = [
        _make_record(room_id=9500 + i, user1_npid="regular", user2_npid=f"guest{i}", created_dt=now - timedelta(minutes=i))
        for i in range(90)
    ]
    await adapter.record_snapshot(db_session, spar + regular)


@pytest.mark.asyncio
async def test_weekly_top_ranks_by_match_count(adapter, db_session):
    await _record_weekly_matches(adapter, db_session)

    top = await adapter.get_weekly_top_players(db_session, limit=3)

    # The two testers tie, and a tie has no defined order.
    assert {(p.npid, p.match_count) for p in top[:2]} == {("tester_a", 100), ("tester_b", 100)}
    assert (top[2].npid, top[2].match_count) == ("regular", 90)


@pytest.mark.asyncio
async def test_weekly_top_skips_excluded_npids_before_the_limit(adapter, db_session):
    """Excluded accounts leave no gap: the next player moves up into the limit.

    Matched case-insensitively, as RPCN usernames are.
    """
    await _record_weekly_matches(adapter, db_session)

    top = await adapter.get_weekly_top_players(db_session, limit=1, excluded_npids=["TESTER_A", "tester_b"])

    assert [p.npid for p in top] == ["regular"]
