"""Tests for the independent match-history collector loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _rank_match(room_id, npid1, npid2, rank_id=10):
    from matching.models import Rank, RoomInfoDTO, RoomType
    from rpcn_client.models import UserInfo

    room = RoomInfoDTO.phantom(npid1, npid1.title(), RoomType.RANK_MATCH, Rank(id=rank_id))
    room.room_id = room_id
    room.current_members = 2
    room.users = [
        UserInfo(npid=npid1, online_name=npid1.title(), avatar_url=""),
        UserInfo(npid=npid2, online_name=npid2.title(), avatar_url=""),
    ]
    return room


def _observation(rank_matches=(), **counts):
    from matching.models import ActivityObservation

    defaults = dict(rank_player_npids=set(), total_players=0, total_rooms=0, rank_players=0, rank_rooms=0)
    defaults.update(counts)
    return ActivityObservation(rank_matches=list(rank_matches), **defaults)


@pytest.fixture
def collector_io(monkeypatch):
    """Stub RPCN and every history write; tests queue observations on `observe`."""
    from history import collector

    io = MagicMock()
    io.observe = AsyncMock()
    io.record_players = AsyncMock()
    io.record_activity = AsyncMock()
    io.record_matches = AsyncMock()
    monkeypatch.setattr(collector, "collect_activity_observation", io.observe)
    monkeypatch.setattr(collector.history_service, "record_daily_matched_players", io.record_players)
    monkeypatch.setattr(collector.history_service, "record_activity_snapshot", io.record_activity)
    monkeypatch.setattr(collector.history_service, "record_snapshot", io.record_matches)
    return io


def _recorded_room_ids(record_matches):
    return [[record.room_id for record in call.args[0]] for call in record_matches.await_args_list]


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
async def test_collect_once_records_one_observation_as_players_snapshot_and_matches(collector_io):
    from history import collector

    collector_io.observe.return_value = _observation(
        rank_matches=[_rank_match(7, "ranked-a", "ranked-b", rank_id=12)],
        rank_player_npids={"ranked-a", "ranked-b"},
        total_players=12, total_rooms=7, rank_players=3, rank_rooms=2,
    )

    await collector.collect_once()

    collector_io.observe.assert_awaited_once_with("NPWR02973_00")
    recorded_npids, observed_at = collector_io.record_players.await_args.args
    snapshot = collector_io.record_activity.await_args.args[0]
    [match] = collector_io.record_matches.await_args.args[0]
    assert recorded_npids == {"ranked-a", "ranked-b"}
    assert snapshot.observed_at == observed_at
    assert (snapshot.total_players, snapshot.total_rooms) == (12, 7)
    assert (snapshot.rank_players, snapshot.rank_rooms) == (3, 2)
    assert (match.room_id, match.rank_id) == (7, 12)
    assert (match.user1_npid, match.user1_online_name) == ("ranked-a", "Ranked-A")
    assert (match.user2_npid, match.user2_online_name) == ("ranked-b", "Ranked-B")
    assert match.created_dt == observed_at


@pytest.mark.asyncio
async def test_collect_once_records_a_match_only_on_the_cycle_it_first_appears(collector_io):
    from history import collector

    first, second = _rank_match(1, "a", "b"), _rank_match(2, "c", "d")
    collector_io.observe.side_effect = [
        _observation([first]),
        _observation([first, second]),
        _observation([second]),
    ]

    for _ in range(3):
        await collector.collect_once()

    assert _recorded_room_ids(collector_io.record_matches) == [[1], [2]]


@pytest.mark.asyncio
async def test_collect_once_retries_a_match_whose_write_failed(collector_io):
    from history import collector

    match = _rank_match(1, "a", "b")
    collector_io.observe.return_value = _observation([match])
    collector_io.record_matches.side_effect = [RuntimeError("db down"), None]

    with pytest.raises(RuntimeError):
        await collector.collect_once()
    await collector.collect_once()

    assert _recorded_room_ids(collector_io.record_matches) == [[1], [1]]
