"""Tests for matching.matchmaking_tracker state machine."""

import time
from types import SimpleNamespace

import pytest

from matching.events import MatchmakingDetected, MatchmakingResolved
from matching.matchmaking_tracker import update_and_get_matchmaking
from matching.models import Rank, RoomInfoDTO, RoomType


def _make_room(room_id, npid, name="P", members=1, room_type_val=1, users=None):
    """Create a RoomInfoDTO from a SimpleNamespace."""
    ri = SimpleNamespace(
        room_id=room_id, owner_npid=npid, owner_online_name=name,
        current_members=members, max_slots=4,
        int_attrs={4: SimpleNamespace(value=room_type_val)},
        users=users or [],
    )
    return RoomInfoDTO(ri)


def test_first_snapshot_returns_empty(mock_settings):
    rooms = [_make_room(1, "p1")]
    result = update_and_get_matchmaking(rooms)
    assert result == []


def test_disappearing_solo_rank_room_starts_matchmaking(mock_settings, mock_publish):
    # First snapshot: room exists
    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1)])
    # Second snapshot: room gone (but another room present to avoid empty-dict early return)
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    matchmaking_npids = {p.owner_npid for p in phantoms}
    assert "p1" in matchmaking_npids
    detected = [e for e in mock_publish if isinstance(e, MatchmakingDetected)]
    assert len(detected) == 1
    assert detected[0].npid == "p1"


def test_disappearing_player_match_room_ignored(mock_settings, mock_publish):
    # Player match room (room_type_val=0)
    update_and_get_matchmaking([_make_room(1, "p1", room_type_val=0)])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    matchmaking_npids = {p.owner_npid for p in phantoms}
    assert "p1" not in matchmaking_npids
    detected = [e for e in mock_publish if isinstance(e, MatchmakingDetected)]
    assert len(detected) == 0


def test_disappearing_2member_rank_room_ignored(mock_settings, mock_publish):
    # 2-member rank room (gaming) disappearing should not trigger matchmaking
    update_and_get_matchmaking([_make_room(1, "p1", members=2, room_type_val=1)])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    matchmaking_npids = {p.owner_npid for p in phantoms}
    assert "p1" not in matchmaking_npids


def test_found_opponent_resolves(mock_settings, mock_publish):
    # The "found_opponent" path fires when a persisted room transitions to gaming
    # while its owner is in _matchmaking_players. This happens when:
    # - Room A (owned by p1) disappears → p1 enters matchmaking
    # - Room B (also owned by p1) persists and becomes gaming in the SAME snapshot
    # Snapshot 1: p1 has two rooms (room 1 solo, room 2 solo)
    update_and_get_matchmaking([
        _make_room(1, "p1", members=1, room_type_val=1),
        _make_room(2, "p1", members=1, room_type_val=1),
        _make_room(99, "anchor"),
    ])
    # Snapshot 2: room 1 disappears (→ p1 enters matchmaking),
    # room 2 persists and now has 2 members (gaming → found_opponent)
    update_and_get_matchmaking([
        _make_room(2, "p1", members=2, room_type_val=1),
        _make_room(99, "anchor"),
    ])
    resolved = [e for e in mock_publish if isinstance(e, MatchmakingResolved)]
    assert any(r.reason == "found_opponent" for r in resolved)


def test_rejoined_room_resolves(mock_settings, mock_publish):
    # Snapshot 1: solo room + anchor
    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    # Snapshot 2: room disappears -> matchmaking
    update_and_get_matchmaking([_make_room(99, "anchor")])
    # Snapshot 3: player appears in a different room
    update_and_get_matchmaking([_make_room(2, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    resolved = [e for e in mock_publish if isinstance(e, MatchmakingResolved)]
    assert any(r.reason == "rejoined_room" for r in resolved)


def test_expired_entry_evicted(mock_settings, mock_publish, monkeypatch):
    mock_settings.matchmaking_ttl = 60
    base_time = time.time()
    monkeypatch.setattr("matching.matchmaking_tracker.time.time", lambda: base_time)

    # Snapshot 1: solo room + anchor
    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    # Snapshot 2: room disappears -> matchmaking
    update_and_get_matchmaking([_make_room(99, "anchor")])

    # Fast-forward past TTL
    monkeypatch.setattr("matching.matchmaking_tracker.time.time", lambda: base_time + 61)
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    matchmaking_npids = {p.owner_npid for p in phantoms}
    assert "p1" not in matchmaking_npids
    resolved = [e for e in mock_publish if isinstance(e, MatchmakingResolved) and e.reason == "expired"]
    assert len(resolved) == 1


def test_multiple_players_tracked_independently(mock_settings, mock_publish):
    # Two solo rooms + anchor
    update_and_get_matchmaking([_make_room(1, "p1"), _make_room(2, "p2"), _make_room(99, "anchor")])
    # Both disappear, anchor stays
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    matchmaking_npids = {p.owner_npid for p in phantoms}
    assert matchmaking_npids == {"p1", "p2"}


def test_phantom_rooms_correct_fields(mock_settings, mock_publish):
    update_and_get_matchmaking([_make_room(1, "p1", name="Player1"), _make_room(99, "anchor")])
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    p1_phantoms = [p for p in phantoms if p.owner_npid == "p1"]
    assert len(p1_phantoms) == 1
    p = p1_phantoms[0]
    assert p.room_id == 0
    assert p.current_members == 1
    assert p.max_slots == 2
    assert p.owner_npid == "p1"
    assert p.owner_online_name == "Player1"
