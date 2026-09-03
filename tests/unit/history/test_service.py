"""Tests for history.service cached layer."""

import pytest


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
async def test_get_daily_summary_cache_hit(mock_history_repo, monkeypatch):
    from history.service import get_daily_summary
    cached = [{"date": "2026-03-30"}]
    monkeypatch.setattr("history.service.cache_get", lambda key: cached)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: None)
    result = await get_daily_summary(30)
    assert result == cached
    mock_history_repo.get_daily_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_player_stats_cache_hit(mock_history_repo, monkeypatch):
    from history.service import get_player_stats
    cached = {"npid": "p1", "days_active": 3}
    monkeypatch.setattr("history.service.cache_get", lambda key: cached)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: None)
    result = await get_player_stats("p1")
    assert result == cached
    mock_history_repo.get_player_stats.assert_not_awaited()
