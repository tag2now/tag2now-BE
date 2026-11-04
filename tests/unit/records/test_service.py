"""The capture and queue steps of match records, over a stubbed repository."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from history.models import RankRoom
from records.models import CharTally, MatchEvent, MatchOutcome, OpponentRecord, PlayerSave, Side, WeeklyPlayer
from records.ports import RecordsPort
from records.service import RecordsService
from shared.clock import Clock

_NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
# Alice, whose event the queue hands out, sits second.
_ROOM = RankRoom(42, "bob", "alice")


class _Fixed(Clock):
    def now(self) -> datetime:
        return _NOW


def _answer(data_id=101, wins=11, npid="alice") -> dict:
    return {
        "npid": npid,
        "data_id": data_id,
        "saved_utc": "2026-11-02 12:00:00",
        "wins": wins,
        "losses": 5,
        "own_chars": [],
        "chars": [{"id": 0, "wins": wins, "losses": 5}],
    }


def _state(data_id=100, wins=10) -> PlayerSave:
    return PlayerSave("alice", data_id, _NOW, wins, 5, {0: CharTally(wins, 5)})


def _event() -> MatchEvent:
    return MatchEvent(1, "alice", MatchOutcome.WIN, (0,), _NOW)


@pytest.fixture
def repo():
    repo = AsyncMock(spec=RecordsPort)
    repo.latest_data_id.return_value = 100
    repo.lock_state.return_value = _state()
    repo.claim_event.return_value = _event()
    repo.fill_side.return_value = False
    return repo


@pytest.fixture
def saves():
    saves = AsyncMock()
    saves.read_changed.return_value = [_answer()]
    return saves


@pytest.fixture
def history():
    history = AsyncMock()
    history.rank_room.return_value = _ROOM
    return history


@pytest.fixture
def service(repo, saves, history):
    session = MagicMock()

    @asynccontextmanager
    async def scope():
        yield

    session.begin = scope
    session.begin_nested = scope

    @asynccontextmanager
    async def sessions():
        yield session

    return RecordsService(repo, sessions, saves, history, _Fixed())


# --- capture --------------------------------------------------------------------


async def test_capture_reads_a_little_behind_the_newest_save(service, saves):
    await service.capture()
    saves.read_changed.assert_awaited_once_with(84, 200)


async def test_capture_starts_from_the_beginning(service, repo, saves):
    repo.latest_data_id.return_value = 3
    await service.capture()
    saves.read_changed.assert_awaited_once_with(0, 200)


async def test_a_finished_match_is_queued_with_the_new_state(service, repo):
    await service.capture()
    assert repo.save_state.await_args.args[1].data_id == 101
    assert repo.add_event.await_args.args[2].outcome is MatchOutcome.WIN


async def test_a_first_save_is_the_baseline_and_no_match(service, repo):
    repo.lock_state.return_value = None
    await service.capture()
    repo.save_state.assert_awaited_once()
    repo.add_event.assert_not_awaited()


async def test_a_save_with_no_change_moves_the_state_only(service, repo, saves):
    saves.read_changed.return_value = [_answer(wins=10)]
    await service.capture()
    repo.save_state.assert_awaited_once()
    repo.add_event.assert_not_awaited()


async def test_a_save_already_compared_is_skipped(service, repo, saves):
    saves.read_changed.return_value = [_answer(data_id=100)]
    await service.capture()
    repo.save_state.assert_not_awaited()
    repo.add_event.assert_not_awaited()


async def test_a_jump_is_counted_and_queues_nothing(service, repo, saves):
    saves.read_changed.return_value = [_answer(wins=13)]
    await service.capture()
    assert repo.save_state.await_args.args[2] is True
    repo.add_event.assert_not_awaited()


async def test_one_bad_save_holds_up_no_other(service, repo, saves):
    saves.read_changed.return_value = [{"data_id": 101}, _answer(data_id=102)]
    await service.capture()
    assert repo.save_state.await_args.args[1].data_id == 102


# --- queue ----------------------------------------------------------------------


async def test_an_empty_queue_says_so(service, repo):
    repo.claim_event.return_value = None
    assert await service.process_next() is False


async def test_the_first_event_of_a_match_records_it_on_the_player_s_side(service, repo):
    assert await service.process_next() is True
    assert repo.lock_room.await_args.args[1] == 42
    assert repo.add_match.await_args.args[2:] == (_ROOM, Side.P2, Side.P2)
    repo.finish_event.assert_awaited_once()


async def test_the_second_event_fills_its_side_and_records_no_new_match(service, repo):
    repo.fill_side.return_value = True
    await service.process_next()
    assert repo.fill_side.await_args.args[2:] == (_ROOM, Side.P2, Side.P2)
    repo.add_match.assert_not_awaited()
    repo.finish_event.assert_awaited_once()


async def test_a_match_outside_any_known_room_puts_the_player_on_1p(service, repo, history):
    history.rank_room.return_value = None
    await service.process_next()
    assert repo.add_match.await_args.args[2:] == (None, Side.P1, Side.P1)
    repo.lock_room.assert_not_awaited()
    repo.fill_side.assert_not_awaited()
    repo.finish_event.assert_awaited_once()


async def test_a_failure_schedules_a_retry_instead_of_finishing(service, repo, history):
    history.rank_room.side_effect = RuntimeError("database hiccup")
    assert await service.process_next() is True
    repo.finish_event.assert_not_awaited()
    repo.fail_event.assert_awaited_once()
    assert repo.fail_event.await_args.args[2] == "database hiccup"


# --- weekly top -----------------------------------------------------------------


@pytest.fixture
def cache(monkeypatch):
    store = {}
    monkeypatch.setattr("records.service.cache_get", store.get)
    monkeypatch.setattr("records.service.cache_set", lambda key, value, ttl: store.__setitem__(key, value))
    monkeypatch.setattr(
        "records.service.get_settings",
        lambda: SimpleNamespace(ranking_excluded_npids=["tester"], cache_ttl_activity=300, cache_ttl_player_hours=300),
    )
    return store


async def test_the_weekly_top_counts_the_last_seven_days_without_excluded_players(service, repo, cache):
    repo.weekly_top_players.return_value = [WeeklyPlayer("alice", "Alice", 3, 2, 1)]

    top = await service.weekly_top_players(10)

    assert top == repo.weekly_top_players.return_value
    _, since, limit, excluded = repo.weekly_top_players.await_args.args
    assert (since, limit, excluded) == (_NOW - timedelta(days=7), 10, ["tester"])
    assert cache["records:weekly_top:10"] == top


async def test_a_cached_weekly_top_reads_nothing(service, repo, cache):
    cache["records:weekly_top:10"] = [{"npid": "alice"}]

    assert await service.weekly_top_players(10) == [{"npid": "alice"}]
    repo.weekly_top_players.assert_not_awaited()


# --- frequent opponents ---------------------------------------------------------


async def test_frequent_opponents_count_the_days_asked_for_and_keep_four(service, repo, cache):
    repo.frequent_opponents.return_value = [OpponentRecord("bob", "Bob", 3, 2, 1)]

    opponents = await service.frequent_opponents("alice", 30)

    assert opponents == repo.frequent_opponents.return_value
    _, npid, since, limit = repo.frequent_opponents.await_args.args
    assert (npid, since, limit) == ("alice", _NOW - timedelta(days=30), 4)
    assert cache["records:opponents:alice:30"] == opponents


async def test_cached_frequent_opponents_read_nothing(service, repo, cache):
    cache["records:opponents:alice:7"] = [{"npid": "bob"}]

    assert await service.frequent_opponents("alice", 7) == [{"npid": "bob"}]
    repo.frequent_opponents.assert_not_awaited()
