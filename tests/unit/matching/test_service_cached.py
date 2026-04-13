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
async def test_get_rooms_all_publishes_activity_snapshot(mock_cache, mock_game_repo, monkeypatch):
    from matching.service import get_rooms_all
    from matching.models import RoomInfoDTO
    monkeypatch.setattr("matching.service.get_server_world_tree", lambda com_id: {"1": [10]})
    room = RoomInfoDTO.phantom("p1", "P1", RoomType.RANK_MATCH, None)
    mock_game_repo.search_rooms_all.return_value = [room]

    published = []
    monkeypatch.setattr("matching.service.publish", lambda e: published.append(e))
    monkeypatch.setattr("matching.service.update_and_get_matchmaking", lambda rooms: [])

    result = await get_rooms_all("NPWR02973_00")
    assert len(published) == 1
    from matching.events import ActivitySnapshot
    assert isinstance(published[0], ActivitySnapshot)


def test_get_leaderboard_cache_miss(mock_cache, mock_game_repo):
    from matching.service import get_leaderboard
    from matching.models import TTT2LeaderboardResult
    mock_game_repo.get_leaderboard.return_value = TTT2LeaderboardResult(
        total_records=1, last_sort_date=0, entries=[],
    )
    result = get_leaderboard("NPWR02973_00", 4, 10)
    assert result["total_records"] == 1
    mock_game_repo.get_leaderboard.assert_called_once()


@pytest.mark.asyncio
async def test_lookup_player_aggregates_sources(mock_cache, monkeypatch):
    from matching.service import lookup_player
    from history.models import PlayerStats

    # Mock history service
    mock_stats = PlayerStats(npid="p1", days_active=5, times_seen=20, first_seen=None, last_seen=None)
    monkeypatch.setattr("history.service.get_player_stats", AsyncMock(return_value=mock_stats))
    monkeypatch.setattr("history.service.get_player_hours", AsyncMock(return_value=[14, 15]))

    # No cached rooms
    monkeypatch.setattr("matching.service.cache_get", lambda key: None)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: None)

    result = await lookup_player("p1")
    assert result.npid == "p1"
    assert result.usual_playing_hours_kst == [14, 15]
    assert result.online_status.is_online is False
