"""Tests for matching.matchmaking_tracker state machine."""

import time
from types import SimpleNamespace

from rpcn_client import UserInfo

import pytest

from matching.matchmaking_tracker import update_and_get_matchmaking
from matching.models import Rank, RoomInfoDTO, RoomType


def _make_user(name, npid=None):
    return UserInfo(npid=npid or name, online_name=name, avatar_url="")


def _make_room(room_id, npid, name=None, members=1, room_type_val=1, users=None):
    """Create a RoomInfoDTO. name defaults to npid. users defaults to [owner]."""
    name = name or npid
    if users is None:
        users = [_make_user(name, npid)]
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


def _searching(phantoms):
    return {p.owner_online_name for p in phantoms}


def test_disappearing_solo_rank_room_starts_matchmaking(mock_settings):
    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1)])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    assert _searching(phantoms) == {"p1"}


def test_disappearing_2member_rank_room_starts_matchmaking(mock_settings):
    # 2-member RANK_MATCH room disappearing should trigger matchmaking for all users
    update_and_get_matchmaking([_make_room(1, "p1", members=2, room_type_val=1,
                                           users=[_make_user("p1"), _make_user("p2")])])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    assert _searching(phantoms) == {"p1", "p2"}


def test_disappearing_player_match_room_ignored(mock_settings):
    # Player match room (room_type_val=0)
    update_and_get_matchmaking([_make_room(1, "p1", room_type_val=0)])
    phantoms = update_and_get_matchmaking([_make_room(99, "other")])
    assert phantoms == []


def test_player_in_a_match_again_leaves_matchmaking(mock_settings):
    # Snapshot 1: p1 has two rooms (room 1 solo, room 2 solo)
    update_and_get_matchmaking([
        _make_room(1, "p1", members=1, room_type_val=1),
        _make_room(2, "p1", members=1, room_type_val=1),
        _make_room(99, "anchor"),
    ])
    # Snapshot 2: room 1 disappears (p1 would be searching), but room 2
    # persists with an opponent in it, so p1 is playing, not searching
    phantoms = update_and_get_matchmaking([
        _make_room(2, "p1", members=2, room_type_val=1),
        _make_room(99, "anchor"),
    ])
    assert phantoms == []


def test_player_back_in_a_room_leaves_matchmaking(mock_settings):
    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    searching = update_and_get_matchmaking([_make_room(99, "anchor")])
    rejoined = update_and_get_matchmaking([_make_room(2, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    assert _searching(searching) == {"p1"}
    assert rejoined == []


def test_expired_entry_evicted(mock_settings, monkeypatch):
    mock_settings.matchmaking_ttl = 60
    base_time = time.time()
    monkeypatch.setattr("matching.matchmaking_tracker.time.time", lambda: base_time)

    update_and_get_matchmaking([_make_room(1, "p1", members=1, room_type_val=1), _make_room(99, "anchor")])
    searching = update_and_get_matchmaking([_make_room(99, "anchor")])

    monkeypatch.setattr("matching.matchmaking_tracker.time.time", lambda: base_time + 61)
    expired = update_and_get_matchmaking([_make_room(99, "anchor")])
    assert _searching(searching) == {"p1"}
    assert expired == []


def test_multiple_players_tracked_independently(mock_settings):
    update_and_get_matchmaking([_make_room(1, "p1"), _make_room(2, "p2"), _make_room(99, "anchor")])
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    matchmaking_names = {p.owner_online_name for p in phantoms}
    assert matchmaking_names == {"p1", "p2"}


def test_phantom_rooms_correct_fields(mock_settings):
    update_and_get_matchmaking([_make_room(1, "p1", name="Player1"), _make_room(99, "anchor")])
    phantoms = update_and_get_matchmaking([_make_room(99, "anchor")])
    p1_phantoms = [p for p in phantoms if p.owner_online_name == "Player1"]
    assert len(p1_phantoms) == 1
    p = p1_phantoms[0]
    assert p.room_id == 0
    assert p.current_members == 1
    assert p.max_slots == 2
    assert p.owner_online_name == "Player1"


def test_phantom_survives_a_snapshot_with_no_rooms(mock_settings):
    """An empty server is a real observation, not a missing baseline."""
    update_and_get_matchmaking([_make_room(1, "p1")])
    update_and_get_matchmaking([])
    phantoms = update_and_get_matchmaking([])
    assert {p.owner_online_name for p in phantoms} == {"p1"}
