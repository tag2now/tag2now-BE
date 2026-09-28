"""Tests for matching.matchmaking_tracker.

A player in the matchmaking loop is hosting (own solo rank room, visible),
searching (no room of their own, invisible) or in a match (two-member rank
room, visible). Only searching players get a phantom room.
"""

from types import SimpleNamespace

import pytest

from matching.matchmaking_tracker import update_and_get_phantoms
from matching.models import RoomInfoDTO, RoomType
from rpcn_client import UserInfo

T0 = 1_000_000.0


def _room(room_id, *npids, rank_id):
    """A room as RPCN lists it. rank_id 0 is a player match; members follow users."""
    info = SimpleNamespace(
        room_id=room_id, owner_npid=npids[0], owner_online_name=npids[0].title(),
        current_members=len(npids), max_slots=2,
        int_attrs={4: SimpleNamespace(value=rank_id)},
        users=[UserInfo(npid=npid, online_name=npid.title(), avatar_url="") for npid in npids],
    )
    return RoomInfoDTO(info)


def hosting(room_id, npid, rank_id=10):
    return _room(room_id, npid, rank_id=rank_id)


def in_match(room_id, host, guest, rank_id=10):
    return _room(room_id, host, guest, rank_id=rank_id)


def player_match(room_id, *npids):
    return _room(room_id, *npids, rank_id=0)


def _phantom_owners(phantoms):
    return {p.owner_npid for p in phantoms}


@pytest.fixture
def clock(monkeypatch, mock_settings):
    """A settable time.time(), with matchmaking_ttl at 60 s."""
    mock_settings.matchmaking_ttl = 60
    now = SimpleNamespace(value=T0)
    monkeypatch.setattr("matching.matchmaking_tracker.time.time", lambda: now.value)
    return now


# -- Baseline ----------------------------------------------------------------

def test_first_snapshot_has_nothing_to_compare_so_no_phantoms(mock_settings):
    assert update_and_get_phantoms([hosting(1, "p1")]) == []


def test_phantom_survives_a_snapshot_with_no_rooms(mock_settings):
    """An empty server is a real observation, not a missing baseline."""
    update_and_get_phantoms([hosting(1, "p1")])
    update_and_get_phantoms([])

    assert _phantom_owners(update_and_get_phantoms([])) == {"p1"}


# -- Entering searching --------------------------------------------------------

def test_host_whose_room_disappears_becomes_a_phantom(mock_settings):
    update_and_get_phantoms([hosting(1, "p1")])

    assert _phantom_owners(update_and_get_phantoms([])) == {"p1"}


def test_both_players_become_phantoms_when_their_match_room_disappears(mock_settings):
    update_and_get_phantoms([in_match(1, "p1", "p2")])

    assert _phantom_owners(update_and_get_phantoms([])) == {"p1", "p2"}


def test_player_match_room_disappearing_makes_no_phantom(mock_settings):
    update_and_get_phantoms([player_match(1, "p1", "p2")])

    assert update_and_get_phantoms([]) == []


def test_phantom_is_a_solo_rank_room_at_the_rank_of_the_room_left(mock_settings):
    update_and_get_phantoms([hosting(1, "p1", rank_id=5)])

    [phantom] = update_and_get_phantoms([])

    assert (phantom.owner_npid, phantom.owner_online_name) == ("p1", "P1")
    assert (phantom.room_id, phantom.current_members, phantom.max_slots) == (0, 1, 2)
    assert phantom.room_type == RoomType.RANK_MATCH
    assert phantom.rank_info.id == 5


# -- Leaving searching ---------------------------------------------------------

def test_phantom_who_hosts_again_is_no_longer_a_phantom(mock_settings):
    update_and_get_phantoms([hosting(1, "p1")])
    update_and_get_phantoms([])

    assert update_and_get_phantoms([hosting(2, "p1")]) == []


def test_phantom_who_joins_a_match_is_no_longer_a_phantom(mock_settings):
    update_and_get_phantoms([hosting(1, "p1"), hosting(5, "p2")])
    update_and_get_phantoms([hosting(5, "p2")])

    assert update_and_get_phantoms([in_match(5, "p2", "p1")]) == []


def test_host_who_joins_a_match_within_one_poll_never_shows_as_a_phantom(mock_settings):
    """p1's own room vanishing and p1 appearing in p2's room arrive in the same snapshot."""
    update_and_get_phantoms([hosting(1, "p1"), hosting(5, "p2")])

    assert update_and_get_phantoms([in_match(5, "p2", "p1")]) == []


def test_phantom_lasts_until_the_ttl_then_expires(clock):
    update_and_get_phantoms([hosting(1, "p1")])
    update_and_get_phantoms([])

    clock.value = T0 + 60
    assert _phantom_owners(update_and_get_phantoms([])) == {"p1"}
    clock.value = T0 + 61
    assert update_and_get_phantoms([]) == []


# -- Independence --------------------------------------------------------------

def test_players_are_tracked_independently(mock_settings):
    update_and_get_phantoms([hosting(1, "p1"), hosting(2, "p2")])

    assert _phantom_owners(update_and_get_phantoms([hosting(2, "p2")])) == {"p1"}
    assert _phantom_owners(update_and_get_phantoms([hosting(3, "p1")])) == {"p2"}
