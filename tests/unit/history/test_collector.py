"""Tests for the independent match-history collector loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_collector_retries_after_a_failed_collection(monkeypatch):
    from history import collector

    attempts = AsyncMock(side_effect=[RuntimeError("rpcn unavailable"), None, asyncio.CancelledError])
    sleep = AsyncMock()
    settings = MagicMock(match_history_collection_interval_seconds=30)
    monkeypatch.setattr(collector, "collect_once", attempts)
    monkeypatch.setattr(collector.asyncio, "sleep", sleep)
    monkeypatch.setattr(collector, "get_settings", lambda: settings)

    with pytest.raises(asyncio.CancelledError):
        await collector.run_collector()

    assert attempts.await_count == 3
    assert sleep.await_args_list[0].args == (30,)
    assert sleep.await_args_list[1].args == (30,)


@pytest.mark.asyncio
async def test_collect_once_records_one_observation_as_daily_players_and_peak_snapshot(monkeypatch):
    from history import collector
    from matching.models import ActivityObservation

    observation = ActivityObservation(
        rank_player_npids={"ranked-a", "ranked-b"},
        total_players=12,
        total_rooms=7,
        rank_players=3,
        rank_rooms=2,
    )
    collect = AsyncMock(return_value=observation)
    record_players = AsyncMock()
    record_snapshot = AsyncMock()
    monkeypatch.setattr(collector, "collect_activity_observation", collect)
    monkeypatch.setattr(collector.history_service, "record_daily_matched_players", record_players)
    monkeypatch.setattr(collector.history_service, "record_activity_snapshot", record_snapshot)

    await collector.collect_once()

    collect.assert_awaited_once_with("NPWR02973_00")
    recorded_npids, observed_at = record_players.await_args.args
    snapshot = record_snapshot.await_args.args[0]
    assert recorded_npids == {"ranked-a", "ranked-b"}
    assert snapshot.observed_at == observed_at
    assert (snapshot.total_players, snapshot.total_rooms) == (12, 7)
    assert (snapshot.rank_players, snapshot.rank_rooms) == (3, 2)
