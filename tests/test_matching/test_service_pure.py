"""Tests for pure domain functions in matching.service."""

import struct

from matching.models import RoomInfoDTO, RoomType, _GAME_INFO_FMT, _GAME_INFO_SIZE
from matching.service import _group_rooms_by_type, format_score_entry, parse_game_info


def _make_game_info_bytes(c1_id=0, c2_id=1, c1_rank=10, c2_rank=5, c1_w=50, c2_w=30, c1_l=20, c2_l=10):
    return struct.pack(_GAME_INFO_FMT, c1_id, c2_id, c1_rank, c2_rank, c1_w, c2_w, c1_l, c2_l)


def test_parse_game_info_valid_data():
    data = _make_game_info_bytes()
    info = parse_game_info(data)
    assert info is not None
    assert info.main_char_info.char_id == 0
    assert info.main_char_info.name == "Paul"
    assert info.sub_char_info.char_id == 1
    assert info.sub_char_info.name == "Law"
    assert info.main_char_info.wins == 50
    assert info.sub_char_info.losses == 10


def test_parse_game_info_short_data():
    result = parse_game_info(b"\x00" * 5)
    assert result is None


def test_parse_game_info_exact_minimum():
    data = _make_game_info_bytes()
    assert len(data) == _GAME_INFO_SIZE
    info = parse_game_info(data)
    assert info is not None


def test_format_score_entry_with_game_info():
    from types import SimpleNamespace
    entry = SimpleNamespace(
        rank=1, np_id="p1", online_name="P1", score=9999,
        pc_id=0, record_date=0, has_game_data=True, comment="",
        game_info=_make_game_info_bytes(),
    )
    # ScoreEntry.__str__ is defined on the real class; we just need format_score_entry not to crash
    # and to include the ">>" game info line
    formatted = format_score_entry(entry)
    assert ">>" in formatted


def test_format_score_entry_without_game_info():
    from types import SimpleNamespace
    entry = SimpleNamespace(
        rank=1, np_id="p1", online_name="P1", score=9999,
        pc_id=0, record_date=0, has_game_data=False, comment="",
        game_info=None,
    )
    formatted = format_score_entry(entry)
    assert ">>" not in formatted


def test_group_rooms_by_type():
    pm = RoomInfoDTO.phantom("p1", "P1", RoomType.PLAYER_MATCH, None)
    rm = RoomInfoDTO.phantom("p2", "P2", RoomType.RANK_MATCH, None)
    grouped = _group_rooms_by_type([pm, rm])
    assert len(grouped["player_match"]) == 1
    assert len(grouped["rank_match"]) == 1
    assert grouped["player_match"][0].owner_npid == "p1"
