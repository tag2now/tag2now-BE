"""Tests for matching.matchmaking_tracker state machine."""

import time
from types import SimpleNamespace

import pytest

from matching.events import MatchmakingDetected, MatchmakingResolved
from matching.matchmaking_tracker import update_and_get_matchmaking
from matching.models import Rank, RoomInfoDTO, RoomType


def _make_user(name):
    return SimpleNamespace(online_name=name)


def _make_room(room_id, npid, name=None, members=1, room_type_val=1, users=None):
    """Create a RoomInfoDTO. name defaults to npid. users defaults to [owner]."""
    name = name or npid
    if users is None:
        users = [_make_user(name)]
    ri = SimpleNamespace(
        room_id=room_id, owner_npid=npid, owner_online_name=name,
        current_members=members, max_slots=4,
        int_attrs={4: SimpleNamespace(value=room_type_val)},
        users=users,
    )
    return RoomInfoDTO(ri)


def test_first_snapshot_returns_empty(mock_settings):
    rooms = [_make_room(1, "p1")]
    result = update_and_get_matchmaking(rooms)
    assert result == []


def test_disappearing_solo_rank_room_starts_matchmaking(mock_settings, mock_publish):
    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1)])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    matchmaking_names = {p.owner_online_name for p in phantoms}
    assert "p1" in matchmaking_names
    detected = [e for e in mock_publish if isinstance(e, MatchmakingDetected)]
    assert len(detected) == 1
    assert detected[0].online_name == "p1"


def test_disappearing_2member_rank_room_starts_matchmaking(mock_settings, mock_publish):
    # 2-member RANK_MATCH room disappearing should trigger matchmaking for all users
    update_and_get_matchmaking([_make_room(1, "p1", members=2, room_type_val=1,
                                           users=[_make_user("p1"), _make_user("p2")])])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    matchmaking_names = {p.owner_online_name for p in phantoms}
    assert "p1" in matchmaking_names
    assert "p2" in matchmaking_names


def test_disappearing_player_match_room_ignored(mock_settings, mock_publish):
    # Player match room (room_type_val=0)
    update_and_get_matchmaking([_make_room(1, "p1", room_type_val=0)])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    matchmaking_names = {p.owner_online_name for p in phantoms}
    assert "p1" not in matchmaking_names
    detected = [e for e in mock_publish if isinstance(e, MatchmakingDetected)]
    assert len(detected) == 0


def test_found_opponent_resolves(mock_settings, mock_publish):
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
    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    update_and_get_matchmaking([_make_room(99, "anchor")])
    update_and_get_matchmaking([_make_room(2, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    resolved = [e for e in mock_publish if isinstance(e, MatchmakingResolved)]
    assert any(r.reason == "rejoined_room" for r in resolved)


def test_expired_entry_evicted(mock_settings, mock_publish, monkeypatch):
    mock_settings.matchmaking_ttl = 60
    base_time = time.time()
    monkeypatch.setattr("matching.matchmaking_tracker.time.time", lambda: base_time)

    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    update_and_get_matchmaking([_make_room(99, "anchor")])

    monkeypatch.setattr("matching.matchmaking_tracker.time.time", lambda: base_time + 61)
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    matchmaking_names = {p.owner_online_name for p in phantoms}
    assert "p1" not in matchmaking_names
    resolved = [e for e in mock_publish if isinstance(e, MatchmakingResolved) and e.reason == "expired"]
    assert len(resolved) == 1


def test_multiple_players_tracked_independently(mock_settings, mock_publish):
    update_and_get_matchmaking([_make_room(1, "p1"), _make_room(2, "p2"), _make_room(99, "anchor")])
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    matchmaking_names = {p.owner_online_name for p in phantoms}
    assert matchmaking_names == {"p1", "p2"}


def test_phantom_rooms_correct_fields(mock_settings, mock_publish):
    update_and_get_matchmaking([_make_room(1, "p1", name="Player1"), _make_room(99, "anchor")])
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    p1_phantoms = [p for p in phantoms if p.owner_online_name == "Player1"]
    assert len(p1_phantoms) == 1
    p = p1_phantoms[0]
    assert p.room_id == 0
    assert p.current_members == 1
    assert p.max_slots == 2
    assert p.owner_online_name == "Player1"
