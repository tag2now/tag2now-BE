"""Tests for cached application services in matching.service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from matching.models import RoomType


@pytest.fixture
def mock_game_repo(monkeypatch):
    repo = MagicMock()
    monkeypatch.setattr("matching.service.get_game_server_repo", lambda: repo)
    return repo


def test_get_server_world_tree_cache_miss(mock_cache, mock_game_repo):
    from matching.service import get_server_world_tree
    mock_game_repo.get_server_world_tree.return_value = {1: [10, 20], 2: [30]}
    result = get_server_world_tree("NPWR02973_00")
    assert result == {"1": [10, 20], "2": [30]}
    mock_game_repo.get_server_world_tree.assert_called_once()


def test_get_server_world_tree_cache_hit(mock_game_repo, monkeypatch):
    from matching.service import get_server_world_tree
    cached = {"1": [10, 20]}
    monkeypatch.setattr("matching.service.cache_get", lambda key: cached)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: None)
    result = get_server_world_tree("NPWR02973_00")
    assert result == cached
    mock_game_repo.get_server_world_tree.assert_not_called()


@pytest.mark.asyncio
async def test_get_rooms_all_groups_rooms_and_merges_matchmaking_phantoms(mock_cache, mock_game_repo, monkeypatch):
    from matching.models import Rank, RoomInfoDTO
    from matching.service import get_rooms_all
    monkeypatch.setattr("matching.service.get_server_world_tree", lambda com_id: {"1": [10]})
    ranked = RoomInfoDTO.phantom("ranked", "Ranked", RoomType.RANK_MATCH, Rank(id=5))
    casual = RoomInfoDTO.phantom("casual", "Casual", RoomType.PLAYER_MATCH, None)
    searching = RoomInfoDTO.phantom("searching", "Searching", RoomType.RANK_MATCH, Rank(id=2))
    mock_game_repo.search_rooms_all.return_value = [ranked, casual]
    monkeypatch.setattr("matching.service.update_and_get_phantoms", lambda rooms: [searching])

    result = await get_rooms_all("NPWR02973_00")

    assert [r["owner_npid"] for r in result["player_match"]] == ["casual"]
    assert [r["owner_npid"] for r in result["rank_match"]] == ["searching", "ranked"]


@pytest.mark.asyncio
async def test_collect_activity_observation_bypasses_http_cache(mock_game_repo, monkeypatch):
    from matching.models import Rank, RoomInfoDTO
    from matching.service import collect_activity_observation
    from rpcn_client.models import UserInfo

    monkeypatch.setattr("matching.service.get_server_world_tree", lambda com_id: {"1": [10]})
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

    observation = await collect_activity_observation("NPWR02973_00")

    assert observation.rank_player_npids == {"solo", "first", "second"}
    assert (observation.total_players, observation.total_rooms) == (4, 4)
    assert (observation.rank_players, observation.rank_rooms) == (3, 2)
    assert observation.rank_matches == [full_ranked]
    mock_game_repo.search_rooms_all.assert_called_once_with("NPWR02973_00", [10])


def test_get_leaderboard_cache_miss(mock_cache, mock_game_repo):
    from matching.service import get_leaderboard
    from matching.models import TTT2LeaderboardResult
    mock_game_repo.get_leaderboard.return_value = TTT2LeaderboardResult(
        total_records=1, last_sort_date=0, entries=[],
    )
    result = get_leaderboard("NPWR02973_00", 4, 10)
    assert result["total_records"] == 1
    mock_game_repo.get_leaderboard.assert_called_once()


def test_get_leaderboard_fetches_full_size_and_slices(mock_cache, mock_game_repo):
    """A small top-N request still caches the full leaderboard, then slices it."""
    from matching.service import get_leaderboard, LEADERBOARD_CACHE_SIZE
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

    result = get_leaderboard("NPWR02973_00", 4, 5)

    assert [e["rank"] for e in result["entries"]] == [1, 2, 3, 4, 5]
    assert result["total_records"] == 20
    assert mock_game_repo.get_leaderboard.call_args.args[2] == LEADERBOARD_CACHE_SIZE


def test_get_leaderboard_slices_from_cache_without_refetching(mock_game_repo, monkeypatch):
    """A cache hit serves any top-N without calling the repository."""
    from matching.service import get_leaderboard

    cached = {
        "total_records": 3,
        "last_sort_date": 0,
        "entries": [{"rank": 1}, {"rank": 2}, {"rank": 3}],
    }
    monkeypatch.setattr("matching.service.cache_get", lambda key: cached)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: None)

    result = get_leaderboard("NPWR02973_00", 4, 2)

    assert result["entries"] == [{"rank": 1}, {"rank": 2}]
    assert cached["entries"] == [{"rank": 1}, {"rank": 2}, {"rank": 3}]
    mock_game_repo.get_leaderboard.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_player_aggregates_sources(mock_cache, monkeypatch):
    from matching.service import lookup_player
    from history.models import PlayerStats

    # Mock history service
    mock_stats = PlayerStats(npid="p1", days_active=5, times_seen=20, first_seen=None, last_seen=None)
    monkeypatch.setattr("history.service.get_player_stats", AsyncMock(return_value=mock_stats))

    # No cached rooms
    monkeypatch.setattr("matching.service.cache_get", lambda key: None)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: None)

    result = await lookup_player("p1")
    assert result.npid == "p1"
    assert result.usual_playing_hours_kst == []
    assert result.online_status.is_online is False


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


@pytest.mark.asyncio
@pytest.mark.parametrize("npid, in_matchmaking", [
    ("host", True),       # hosting: own solo rank room
    ("searcher", True),   # searching: listed only as a phantom room
    ("guest", True),      # in match: two-member rank room
    ("casual", False),    # player match is not matchmaking
    ("nobody", False),
])
async def test_lookup_player_reads_matchmaking_from_the_cached_room_list(
    mock_game_repo, monkeypatch, npid, in_matchmaking,
):
    """The cache is filled by get_rooms_all itself, so lookup reads the shape it really stores."""
    from history.models import PlayerStats
    from matching.models import Rank, RoomInfoDTO
    from matching.service import get_rooms_all, lookup_player

    store = {}
    monkeypatch.setattr("matching.service.cache_get", store.get)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: store.__setitem__(key, value))
    monkeypatch.setattr("matching.service.get_server_world_tree", lambda com_id: {"1": [10]})
    mock_game_repo.search_rooms_all.return_value = [
        _listed_room(1, "host", rank_id=10),
        _listed_room(2, "owner", "guest", rank_id=10),
        _listed_room(3, "casual", rank_id=0),
    ]
    searcher = RoomInfoDTO.phantom("searcher", "searcher", RoomType.RANK_MATCH, Rank(id=10))
    monkeypatch.setattr("matching.service.update_and_get_phantoms", lambda rooms: [searcher])
    never_recorded = PlayerStats(npid=npid, days_active=0, times_seen=0, first_seen=None, last_seen=None)
    monkeypatch.setattr("history.service.get_player_stats", AsyncMock(return_value=never_recorded))

    await get_rooms_all("NPWR02973_00")
    result = await lookup_player(npid)

    assert result.online_status.is_matchmaking is in_matchmaking
    assert result.online_status.is_online is in_matchmaking
