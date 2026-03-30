"""Tests for history.models dataclasses."""

from datetime import datetime, timezone

from history.models import DailySummary, HourlyActivity, PlayerStats, RoomSnapshotRecord


def test_room_snapshot_record_defaults():
    record = RoomSnapshotRecord(
        room_id=1, room_type="rank_match", owner_npid="p1",
        owner_online_name="P1", current_members=1, max_slots=2,
        is_matchmaking=False,
    )
    assert record.member_npids == []
    assert record.member_online_names == []


def test_room_snapshot_record_with_members():
    record = RoomSnapshotRecord(
        room_id=1, room_type="player_match", owner_npid="p1",
        owner_online_name="P1", current_members=2, max_slots=4,
        is_matchmaking=False,
        member_npids=["p1", "p2"],
        member_online_names=["P1", "P2"],
    )
    assert record.member_npids == ["p1", "p2"]
    assert record.member_online_names == ["P1", "P2"]
    assert record.current_members == 2


def test_hourly_activity_fields():
    ha = HourlyActivity(hour=14, avg_players=3.5, peak_players=7)
    assert ha.hour == 14
    assert ha.avg_players == 3.5
    assert ha.peak_players == 7


def test_daily_summary_fields():
    ds = DailySummary(date="2026-03-30", peak_players=10, avg_players=5.2, peak_rooms=3)
    assert ds.date == "2026-03-30"
    assert ds.peak_players == 10
    assert ds.avg_players == 5.2
    assert ds.peak_rooms == 3


def test_player_stats_defaults_and_populated():
    # Defaults
    ps = PlayerStats(npid="p1", days_active=0, times_seen=0, first_seen=None, last_seen=None)
    assert ps.room_type_counts == {}

    # Populated
    now = datetime.now(timezone.utc)
    ps2 = PlayerStats(
        npid="p1", days_active=5, times_seen=42,
        first_seen=now, last_seen=now,
        room_type_counts={"rank_match": 30, "player_match": 12},
    )
    assert ps2.days_active == 5
    assert ps2.room_type_counts["rank_match"] == 30
