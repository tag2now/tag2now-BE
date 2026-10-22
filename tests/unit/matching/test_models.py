"""Tests for matching.models dataclasses."""

from matching.models import (
    CharInfo,
    Rank,
    RoomInfoDTO,
    RoomType,
)


def test_room_type_enum_values():
    assert RoomType.PLAYER_MATCH.value == "player_match"
    assert RoomType.RANK_MATCH.value == "rank_match"


def test_rank_known_id():
    r = Rank(id=0)
    assert r.name == "Beginner"
    assert r.tier == "숫자단"


def test_rank_unknown_id():
    r = Rank(id=999)
    assert "Unknown" in r.name
    assert r.tier == "Unknown"


def test_char_info_known():
    ci = CharInfo(char_id=0x00, rank_info=Rank(id=10), wins=100, losses=50)
    assert ci.name == "Paul"
    assert ci.wins == 100
    assert ci.losses == 50


def test_char_info_unknown():
    ci = CharInfo(char_id=0xFF, rank_info=Rank(id=0), wins=0, losses=0)
    assert "Unknown" in ci.name


def test_room_info_dto_phantom():
    room = RoomInfoDTO.phantom("p1", "P1", RoomType.RANK_MATCH, Rank(id=20))
    assert room.room_id == 0
    assert room.current_members == 1
    assert room.max_slots == 2
    assert room.owner_npid == "p1"
    assert room.room_type == RoomType.RANK_MATCH
    assert room.rank_info.name == "Berserker"
    assert room.users[0].npid == "p1"
    assert room.users[0].online_name == "P1"
