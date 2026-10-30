"""Comparing saves with the baseline, and answering the board and a player's progress."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from event.baseline import load_baselines
from event.dependencies import event_service
from event.domain import CHARACTER_COUNT, EVENT_START, Baseline, CharState
from event.exceptions import EventClosedError, EventPlayerNotFoundError
from event.service import EventService
from shared.cache import cache_delete_pattern
from shared.clock import Clock

PAUL, LAW, KUMA = 0, 1, 0x0B
FIRST_DAN, SECOND_DAN, THIRD_DAN = 10, 11, 12
LATER = EVENT_START + timedelta(hours=1)


class FixedClock(Clock):
    def __init__(self, now: datetime):
        self.moment = now

    def now(self) -> datetime:
        return self.moment


def player(npid: str = "gosan", rank: int = FIRST_DAN) -> Baseline:
    return Baseline(npid, (CharState(rank, 0, 0),) * CHARACTER_COUNT, rank)


def save(npid: str, rank: int, wins: int = 1, char: int = PAUL) -> dict:
    return {"npid": npid, "chars": [{"id": char, "rank": rank, "wins": wins, "losses": 0}]}


def service(baselines, *saves, now=LATER) -> EventService:
    server = AsyncMock()
    server.read_ranks.return_value = list(saves)
    return EventService(baselines, server, FixedClock(now))


@pytest.fixture(autouse=True)
def empty_cache():
    cache_delete_pattern("event:*")
    yield
    cache_delete_pattern("event:*")


@pytest.fixture
def end_at(monkeypatch):
    from shared.settings import get_settings

    def set_end(moment):
        monkeypatch.setattr(get_settings(), "event_end_at", moment)

    return set_end


async def test_the_board_lists_who_holds_a_condition():
    board = await service([player(), player("other")], save("gosan", THIRD_DAN)).board()

    assert [(a["place"], a["username"], a["gain"]) for a in board["achievers"]] == [(1, "gosan", 2)]
    assert board["achievers"][0]["to_rank"]["name"] == "3rd dan"
    assert board["ended"] is False and board["end_at"] is None


async def test_the_board_says_when_the_event_has_ended(end_at):
    end_at(LATER - timedelta(minutes=1))

    assert (await service([player()]).board())["ended"] is True


async def test_an_account_made_after_the_event_began_is_left_out():
    board = await service([player()], save("newcomer", THIRD_DAN)).board()

    assert board["achievers"] == []


async def test_the_board_leaves_out_excluded_accounts(monkeypatch):
    from shared.settings import get_settings

    monkeypatch.setattr(get_settings(), "ranking_excluded_npids", ["gosan"])

    assert (await service([player()], save("gosan", THIRD_DAN)).board())["achievers"] == []


async def test_a_players_progress_shows_the_main_and_what_they_played():
    chars = (CharState(FIRST_DAN, 0, 0), *[CharState(0, 0, 0)] * (CHARACTER_COUNT - 1))
    baseline = Baseline("gosan", chars, FIRST_DAN)

    answer = await service([baseline], save("gosan", SECOND_DAN, char=LAW)).player("GOSAN")

    assert answer["username"] == "gosan" and answer["main_steps"] == 2
    assert [(s["main"], s["char"]["id"], s["rank"]["rank"]) for s in answer["slots"]] == [
        (True, PAUL, FIRST_DAN),
        (False, LAW, SECOND_DAN),
    ]


async def test_a_player_sees_the_half_they_played_and_not_the_other():
    ranks = [CharState(0, 0, 0)] * CHARACTER_COUNT
    ranks[KUMA] = CharState(FIRST_DAN, 0, 0)
    baseline = Baseline("gosan", tuple(ranks), FIRST_DAN)

    answer = await service([baseline], save("gosan", FIRST_DAN, char=KUMA)).player("gosan")

    assert [s["char"]["character"] for s in answer["slots"]] == ["Kuma"]


async def test_a_player_on_the_board_knows_their_place():
    answer = await service([player()], save("gosan", THIRD_DAN)).player("gosan")

    assert answer["achieved"] is True and answer["place"] == 1


async def test_the_board_and_every_player_come_from_one_read():
    event = service([player(), player("other")], save("gosan", THIRD_DAN))

    await event.board()
    await event.player("gosan")
    await event.player("other")

    assert event._saves.read_ranks.await_count == 1


async def test_a_player_with_no_baseline_is_not_found():
    event = service([player()])

    with pytest.raises(EventPlayerNotFoundError):
        await event.player("nobody")
    event._saves.read_ranks.assert_not_awaited()


async def test_without_a_baseline_the_event_is_closed():
    event = service([])

    with pytest.raises(EventClosedError):
        await event.board()
    with pytest.raises(EventClosedError):
        await event.player("gosan")
    event._saves.read_ranks.assert_not_awaited()


def test_a_baseline_file_loads_with_the_characters_it_leaves_out_empty(tmp_path):
    path = tmp_path / "baseline.json"
    saved = {"npid": "gosan", "account_rank": 27, "new_player": True, "chars": [[LAW, FIRST_DAN, 3, 2]]}
    path.write_text(json.dumps([saved]), encoding="utf-8")

    [baseline] = load_baselines(str(path))

    assert (baseline.npid, baseline.account_rank, baseline.new_player) == ("gosan", 27, True)
    assert baseline.chars[LAW] == CharState(FIRST_DAN, 3, 2)
    assert baseline.chars[PAUL] == CharState(0, 0, 0) and len(baseline.chars) == CHARACTER_COUNT


@pytest.mark.parametrize("content", ["not json", "[{}]", '[{"npid": "gosan", "chars": 1}]'])
def test_a_broken_baseline_file_closes_the_event_rather_than_failing_startup(tmp_path, content):
    path = tmp_path / "baseline.json"
    path.write_text(content, encoding="utf-8")

    assert load_baselines(str(path)) == []


def test_no_baseline_file_closes_the_event(tmp_path):
    assert load_baselines("") == []
    assert load_baselines(str(tmp_path / "missing.json")) == []
    assert load_baselines(str(tmp_path)) == []


async def test_the_board_answers_over_http():
    from app import app

    app.dependency_overrides[event_service] = lambda: service([player()])
    try:
        response = TestClient(app).get("/event")
    finally:
        app.dependency_overrides.pop(event_service, None)

    assert response.status_code == 200
    assert response.json()["capacity"] == 20
