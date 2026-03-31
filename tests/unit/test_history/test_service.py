"""Tests for history.service cached layer."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from history.models import DailySummary, HourlyActivity, PlayerStats, RoomSnapshotRecord


@pytest.mark.asyncio
async def test_record_snapshot_delegates_to_repo(mock_history_repo, sample_snapshot_record):
    from history.service import record_snapshot
    records = [sample_snapshot_record()]
    await record_snapshot(records)
    mock_history_repo.record_snapshot.assert_awaited_once_with(records)


@pytest.mark.asyncio
async def test_get_hourly_activity_cache_miss(mock_history_repo, mock_cache):
    from history.service import get_hourly_activity
    expected = [HourlyActivity(hour=0, avg_players=1.0, peak_players=2)]
    mock_history_repo.get_hourly_activity.return_value = expected
    result = await get_hourly_activity(7)
    assert result == expected
    mock_history_repo.get_hourly_activity.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_get_hourly_activity_cache_hit(mock_history_repo, monkeypatch):
    from history.service import get_hourly_activity
    cached = [{"hour": 0, "avg_players": 1.0, "peak_players": 2}]
    monkeypatch.setattr("history.service.cache_get", lambda key: cached)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: None)
    result = await get_hourly_activity(7)
    assert result == cached
    mock_history_repo.get_hourly_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_daily_summary_cache_miss(mock_history_repo, mock_cache):
    from history.service import get_daily_summary
    expected = [DailySummary(date="2026-03-30", peak_players=10, avg_players=5.0, peak_rooms=3)]
    mock_history_repo.get_daily_summary.return_value = expected
    result = await get_daily_summary(30)
    assert result == expected


@pytest.mark.asyncio
async def test_get_daily_summary_cache_hit(mock_history_repo, monkeypatch):
    from history.service import get_daily_summary
    cached = [{"date": "2026-03-30"}]
    monkeypatch.setattr("history.service.cache_get", lambda key: cached)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: None)
    result = await get_daily_summary(30)
    assert result == cached


@pytest.mark.asyncio
async def test_get_player_stats_cache_miss(mock_history_repo, mock_cache):
    from history.service import get_player_stats
    expected = PlayerStats(npid="p1", days_active=3, times_seen=10, first_seen=None, last_seen=None)
    mock_history_repo.get_player_stats.return_value = expected
    result = await get_player_stats("p1")
    assert result == expected


@pytest.mark.asyncio
async def test_get_player_stats_cache_hit(mock_history_repo, monkeypatch):
    from history.service import get_player_stats
    cached = {"npid": "p1", "days_active": 3}
    monkeypatch.setattr("history.service.cache_get", lambda key: cached)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: None)
    result = await get_player_stats("p1")
    assert result == cached


@pytest.mark.asyncio
async def test_get_player_hours_cache_miss_and_hit(mock_history_repo, monkeypatch):
    from history.service import get_player_hours

    # Cache miss
    monkeypatch.setattr("history.service.cache_get", lambda key: None)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: None)
    mock_history_repo.get_player_hours.return_value = [14, 15, 16]
    result = await get_player_hours("p1")
    assert result == [14, 15, 16]

    # Cache hit
    monkeypatch.setattr("history.service.cache_get", lambda key: [20, 21])
    result = await get_player_hours("p1")
    assert result == [20, 21]
