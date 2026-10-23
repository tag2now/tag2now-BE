"""Tests for cached application services in matching.service."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from matching.models import RoomType
from matching.service import LEADERBOARD_CACHE_SIZE, MatchingService


@pytest.fixture
def mock_game_repo():
    return MagicMock()


@pytest.fixture
def service(mock_game_repo):
    return MatchingService(mock_game_repo)


def _phantoms(*rooms):
    """A tracker stand-in that reports these searching players."""
    return SimpleNamespace(update_and_get_phantoms=lambda current: list(rooms))


def test_get_server_world_tree_cache_miss(service, mock_cache, mock_game_repo):
    mock_game_repo.get_server_world_tree.return_value = {1: [10, 20], 2: [30]}
    result = service.get_server_world_tree("NPWR02973_00")
    assert result == {"1": [10, 20], "2": [30]}
    mock_game_repo.get_server_world_tree.assert_called_once()


def test_get_server_world_tree_cache_hit(service, mock_game_repo, monkeypatch):
    cached = {"1": [10, 20]}
    monkeypatch.setattr("matching.service.cache_get", lambda key: cached)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: None)
    result = service.get_server_world_tree("NPWR02973_00")
    assert result == cached
    mock_game_repo.get_server_world_tree.assert_not_called()


@pytest.mark.asyncio
async def test_get_rooms_all_groups_rooms_and_merges_matchmaking_phantoms(mock_cache, mock_game_repo, monkeypatch):
    from matching.models import Rank, RoomInfoDTO
    ranked = RoomInfoDTO.phantom("ranked", "Ranked", RoomType.RANK_MATCH, Rank(id=5))
    casual = RoomInfoDTO.phantom("casual", "Casual", RoomType.PLAYER_MATCH, None)
    searching = RoomInfoDTO.phantom("searching", "Searching", RoomType.RANK_MATCH, Rank(id=2))
    mock_game_repo.search_rooms_all.return_value = [ranked, casual]
    service = MatchingService(mock_game_repo, tracker=_phantoms(searching))
    monkeypatch.setattr(service, "get_server_world_tree", lambda com_id: {"1": [10]})

    result = await service.get_rooms_all("NPWR02973_00")

    assert [r["owner_npid"] for r in result["player_match"]] == ["casual"]
    assert [r["owner_npid"] for r in result["rank_match"]] == ["searching", "ranked"]


@pytest.mark.asyncio
async def test_collect_activity_observation_bypasses_http_cache(service, mock_game_repo, monkeypatch):
    from matching.models import Rank, RoomInfoDTO
    from rpcn_client.models import UserInfo

    monkeypatch.setattr(service, "get_server_world_tree", lambda com_id: {"1": [10]})
    solo_ranked = RoomInfoDTO.phantom("solo", "Solo", RoomType.RANK_MATCH, Rank(id=1))
    full_ranked = RoomInfoDTO.phantom("first", "First", RoomType.RANK_MATCH, Rank(id=2))
    full_ranked.current_members = 2
    full_ranked.users = [
        UserInfo(npid="first", online_name="First", avatar_url=""),
        UserInfo(npid="second", online_name="Second", avatar_url=""),
    ]
    player_match = RoomInfoDTO.phantom("ignored", "Ignored", RoomType.PLAYER_MATCH, None)
    empty_ranked = RoomInfoDTO.phantom("", "", RoomType.RANK_MATCH, Rank(id=3))
    empty_ranked.current_members = 0
    empty_ranked.users = []
    mock_game_repo.search_rooms_all.return_value = [solo_ranked, full_ranked, player_match, empty_ranked]

    observation = await service.collect_activity_observation("NPWR02973_00")

    assert observation.rank_player_npids == {"solo", "first", "second"}
    assert (observation.total_players, observation.total_rooms) == (4, 4)
    assert (observation.rank_players, observation.rank_rooms) == (3, 2)
    assert observation.rank_matches == [full_ranked]
    mock_game_repo.search_rooms_all.assert_called_once_with("NPWR02973_00", [10])


def test_get_leaderboard_cache_miss(service, mock_cache, mock_game_repo):
    from matching.models import TTT2LeaderboardResult
    mock_game_repo.get_leaderboard.return_value = TTT2LeaderboardResult(
        total_records=1, last_sort_date=0, entries=[],
    )
    result = service.get_leaderboard("NPWR02973_00", 4, 10)
    assert result["total_records"] == 1
    mock_game_repo.get_leaderboard.assert_called_once()


def test_get_leaderboard_fetches_full_size_and_slices(service, mock_cache, mock_game_repo):
    """A small top-N request still caches the full leaderboard, then slices it."""
    from matching.models import TTT2LeaderboardResult, TTT2LeaderboardEntry

    entries = [
        TTT2LeaderboardEntry(
            rank=i, np_id=f"p{i}", online_name=f"P{i}", score=1000 - i,
            pc_id=0, record_date=0, has_game_data=False, comment="", player_info=None,
        )
        for i in range(1, 21)
    ]
    mock_game_repo.get_leaderboard.return_value = TTT2LeaderboardResult(
        total_records=20, last_sort_date=0, entries=entries,
    )

    result = service.get_leaderboard("NPWR02973_00", 4, 5)

    assert [e["rank"] for e in result["entries"]] == [1, 2, 3, 4, 5]
    assert result["total_records"] == 20
    assert mock_game_repo.get_leaderboard.call_args.args[2] == LEADERBOARD_CACHE_SIZE


def test_get_leaderboard_slices_from_cache_without_refetching(service, mock_game_repo, monkeypatch):
    """A cache hit serves any top-N without calling the repository."""

    cached = {
        "total_records": 3,
        "last_sort_date": 0,
        "entries": [{"rank": 1}, {"rank": 2}, {"rank": 3}],
    }
    monkeypatch.setattr("matching.service.cache_get", lambda key: cached)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: None)

    result = service.get_leaderboard("NPWR02973_00", 4, 2)

    assert result["entries"] == [{"rank": 1}, {"rank": 2}]
    assert cached["entries"] == [{"rank": 1}, {"rank": 2}, {"rank": 3}]
    mock_game_repo.get_leaderboard.assert_not_called()



def test_get_leaderboard_drops_excluded_accounts_and_closes_their_gaps(service, mock_cache, mock_game_repo, monkeypatch):
    """Excluded accounts leave no gap: everyone below moves up, and a tie stays a tie."""
    from matching.models import TTT2LeaderboardResult, TTT2LeaderboardEntry
    from shared.settings import get_settings

    monkeypatch.setattr(get_settings(), "ranking_excluded_npids", ["TESTER", "other_tester"])
    board = [(1, "a"), (2, "tester"), (3, "b"), (3, "c"), (5, "Other_Tester"), (6, "d")]
    mock_game_repo.get_leaderboard.return_value = TTT2LeaderboardResult(
        total_records=100, last_sort_date=0, entries=[
            TTT2LeaderboardEntry(
                rank=rank, np_id=npid, online_name=npid, score=0,
                pc_id=0, record_date=0, has_game_data=False, comment="", player_info=None,
            )
            for rank, npid in board
        ],
    )

    result = service.get_leaderboard("NPWR02973_00", 4, 10)

    assert [(e["rank"], e["np_id"]) for e in result["entries"]] == [(1, "a"), (2, "b"), (2, "c"), (4, "d")]
    assert result["total_records"] == 98


def _listed_room(room_id, *npids, rank_id):
    """A room as RPCN lists it. rank_id 0 is a player match."""
    from types import SimpleNamespace
    from matching.models import RoomInfoDTO
    from rpcn_client.models import UserInfo

    return RoomInfoDTO(SimpleNamespace(
        room_id=room_id, owner_npid=npids[0], owner_online_name=npids[0],
        current_members=len(npids), max_slots=2,
        int_attrs={4: SimpleNamespace(value=rank_id)},
        users=[UserInfo(npid=npid, online_name=npid, avatar_url="") for npid in npids],
    ))
