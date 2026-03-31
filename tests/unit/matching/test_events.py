"""Tests for matching.events dataclasses."""

from matching.events import ActivitySnapshot, MatchmakingDetected, MatchmakingResolved
from matching.models import RoomType


def test_matchmaking_detected_fields():
    event = MatchmakingDetected(
        online_name="Player1",
        room_type=RoomType.RANK_MATCH, timestamp=1000.0,
    )
    assert event.online_name == "Player1"
    assert event.room_type == RoomType.RANK_MATCH
    assert event.timestamp == 1000.0


def test_matchmaking_resolved_fields():
    event = MatchmakingResolved(online_name="Player1", reason="found_opponent", timestamp=1001.0)
    assert event.online_name == "Player1"
    assert event.reason == "found_opponent"
    assert event.timestamp == 1001.0


def test_activity_snapshot_default_empty():
    event = ActivitySnapshot()
    assert event.rooms == []
