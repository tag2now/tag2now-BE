"""Tests for matching.models dataclasses."""

from datetime import datetime, timezone

from matching.models import (
    CharInfo,
    PlayerLookupResponse,
    PlayerOnlineStatus,
    Rank,
    RoomInfoDTO,
    RoomType,
    TTT2GameInfo,
    TTT2LeaderboardEntry,
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


def test_ttt2_game_info_from_cache():
    data = {
        "main_char_info": {"char_id": 0, "rank_info": {"id": 10}, "wins": 50, "losses": 20},
        "sub_char_info": {"char_id": 1, "rank_info": {"id": 5}, "wins": 30, "losses": 10},
    }
    info = TTT2GameInfo.from_cache(data)
    assert info.main_char_info.name == "Paul"
    assert info.sub_char_info.name == "Law"


def test_ttt2_leaderboard_entry_from_cache_with_player_info():
    data = {
        "rank": 1, "np_id": "p1", "online_name": "P1", "score": 9999,
        "pc_id": 0, "record_date": 0, "has_game_data": True, "comment": "",
        "player_info": {
            "main_char_info": {"char_id": 0, "rank_info": {"id": 42}, "wins": 100, "losses": 0},
            "sub_char_info": {"char_id": 1, "rank_info": {"id": 42}, "wins": 100, "losses": 0},
        },
    }
    entry = TTT2LeaderboardEntry.from_cache(data)
    assert entry.rank == 1
    assert entry.player_info is not None
    assert entry.player_info.main_char_info.rank_info.name == "True Tekken God"


def test_ttt2_leaderboard_entry_from_cache_without_player_info():
    data = {
        "rank": 2, "np_id": "p2", "score": 5000,
    }
    entry = TTT2LeaderboardEntry.from_cache(data)
    assert entry.player_info is None
    assert entry.online_name == ""


def test_room_info_dto_phantom():
    room = RoomInfoDTO.phantom("p1", "P1", RoomType.RANK_MATCH, Rank(id=20))
    assert room.room_id == 0
    assert room.current_members == 1
    assert room.max_slots == 2
    assert room.owner_npid == "p1"
    assert room.room_type == RoomType.RANK_MATCH
    assert room.rank_info.name == "Berserker"
    assert room.users == []


def test_player_online_status_defaults():
    status = PlayerOnlineStatus(is_online=False, is_matchmaking=False)
    assert status.last_seen is None
    assert status.is_online is False


def test_player_lookup_response_construction():
    status = PlayerOnlineStatus(is_online=True, is_matchmaking=True, last_seen=datetime.now(timezone.utc))
    resp = PlayerLookupResponse(npid="p1", online_status=status, leaderboard=None, usual_playing_hours_kst=[14, 15])
    assert resp.npid == "p1"
    assert resp.online_status.is_matchmaking is True
    assert resp.usual_playing_hours_kst == [14, 15]
