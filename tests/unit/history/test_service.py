"""HistoryService: read-through caching, and writes that invalidate the daily summaries."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cache(monkeypatch):
    """A dict standing in for the cache, recording every deleted pattern."""
    fake = SimpleNamespace(store={}, deleted=[])
    monkeypatch.setattr("history.service.cache_get", fake.store.get)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: fake.store.__setitem__(key, value))
    monkeypatch.setattr("history.service.cache_delete_pattern", fake.deleted.append)
    return fake


async def test_get_hourly_activity_cache_hit(service, repo, cache):
    cache.store["history:hourly:7"] = [{"hour": 0, "avg_players": 1.0, "peak_players": 2}]

    result = await service.get_hourly_activity(7)

    assert result == cache.store["history:hourly:7"]
    repo.get_hourly_activity.assert_not_awaited()


async def test_get_daily_summary_cache_hit(service, repo, cache):
    cache.store["history:daily:30"] = [{"date": "2026-03-30"}]

    result = await service.get_daily_summary(30)

    assert result == cache.store["history:daily:30"]
    repo.get_daily_summary.assert_not_awaited()


async def test_get_player_stats_cache_hit(service, repo, cache):
    cache.store["history:player_stats:p1:30"] = {"npid": "p1", "days_active": 3}

    result = await service.get_player_stats("p1")

    assert result == cache.store["history:player_stats:p1:30"]
    repo.get_player_stats.assert_not_awaited()


async def test_a_cache_miss_reads_the_repo_and_caches_the_result(service, repo, session, cache):
    repo.get_hourly_activity.return_value = [{"hour": 3, "avg_players": 2.0, "peak_players": 4}]

    result = await service.get_hourly_activity(7)

    repo.get_hourly_activity.assert_awaited_once_with(session, 7)
    assert result == repo.get_hourly_activity.return_value
    assert cache.store["history:hourly:7"] == result


async def test_no_participants_writes_nothing(service, repo, cache):
    await service.record_daily_matched_players(set(), NOW)

    repo.record_daily_matched_players.assert_not_awaited()
    assert cache.deleted == []


async def test_recording_participants_invalidates_the_daily_summaries(service, repo, session, cache):
    await service.record_daily_matched_players({"p1", "p2"}, NOW)

    repo.record_daily_matched_players.assert_awaited_once_with(session, {"p1", "p2"}, NOW)
    assert cache.deleted == ["history:daily:*"]


async def test_a_failed_write_leaves_the_daily_summaries_cached(service, repo, cache):
    repo.record_daily_matched_players.side_effect = RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await service.record_daily_matched_players({"p1"}, NOW)

    assert cache.deleted == []
