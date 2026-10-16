"""The current-rank leaderboard, with tag2now-save-admin's server replaced by an httpx mock transport."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from saves import db
from saves.adapters.save_admin_server import SaveAdminServer
from saves.exceptions import SavesUnavailableError
from saves.service import current_rank_board
from shared.cache import DictCache


def _char(id: int, rank: int, points: int = 0) -> dict:
    return {"id": id, "character": f"C{id}", "rank": rank, "rank_name": f"R{rank}", "tier": "t",
            "points": points, "streak": 0, "wins": 1, "losses": 0}


def _player(npid: str, *chars: dict, account_rank: int = 20) -> dict:
    return {"npid": npid, "saved_utc": "2026-10-16 01:02:03", "account_rank": account_rank, "chars": list(chars)}


PLAYERS = [_player("Bob", _char(0, 20)), _player("Alice", _char(3, 25, 100), _char(7, 21))]


def _server(status: int = 200, body: dict | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={"players": PLAYERS} if body is None else body)
    return httpx.MockTransport(handler)


async def _adapter(transport) -> SaveAdminServer:
    adapter = SaveAdminServer("http://save-admin:8000", "key", 1.0, transport=transport)
    await adapter.init()
    return adapter


@pytest.fixture
async def use_server():
    """Install an adapter for the service, and restore whatever was there."""
    previous = db._server
    installed = []

    async def install(transport):
        adapter = await _adapter(transport)
        installed.append(adapter)
        db.set_save_server(adapter)
        return adapter

    yield install
    for adapter in installed:
        await adapter.close()
    db.set_save_server(previous)


@pytest.fixture(autouse=True)
def cache(monkeypatch):
    """A cache of this test's own, so no answer leaks between tests."""
    fresh = DictCache()
    monkeypatch.setattr("saves.service.cache_get", fresh.get)
    monkeypatch.setattr("saves.service.cache_set", fresh.set)
    return fresh


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)  # no `with`: lifespan stays off, the adapter is ours


def _order(board: list[dict]) -> list[tuple[int, str]]:
    return [(e["rank"], e["username"]) for e in board]


# --- adapter ------------------------------------------------------------------

async def test_reads_every_player_with_a_get_and_the_api_key_only():
    seen = []
    adapter = await _adapter(_server(seen=seen))
    assert await adapter.read_top_ranks() == PLAYERS
    request = seen[0]
    assert (request.method, request.url.path) == ("GET", "/players/top-ranks")
    assert request.headers["X-API-Key"] == "key"
    await adapter.close()


@pytest.mark.parametrize("response", [
    (403, {"error": "invalid_api_key", "message": "x"}),
    (500, {"error": "internal_error", "message": "x"}),
])
async def test_a_refusal_is_unavailable(response):
    adapter = await _adapter(_server(*response))
    with pytest.raises(SavesUnavailableError):
        await adapter.read_top_ranks()
    await adapter.close()


# --- ordering -------------------------------------------------------------------

def test_best_character_first_then_the_second():
    board = current_rank_board([
        _player("Low", _char(0, 21), _char(1, 21)),
        _player("Top", _char(0, 25), _char(1, 12)),
        _player("Pair", _char(0, 22), _char(1, 22)),
        _player("Second", _char(0, 22), _char(1, 14)),
    ])
    assert _order(board) == [(1, "Top"), (2, "Pair"), (3, "Second"), (4, "Low")]


def test_points_break_a_tie_of_ranks():
    board = current_rank_board([
        _player("A", _char(0, 22, 100), _char(1, 20, 9000)),
        _player("B", _char(0, 22, 4000), _char(1, 20, 0)),
        _player("C", _char(0, 22, 100), _char(1, 20, 9001)),
    ])
    assert _order(board) == [(1, "B"), (2, "C"), (3, "A")]


def test_equal_standings_share_a_place_and_list_by_name():
    floor = (_char(0, 14, 5000), _char(1, 14, 5000))
    board = current_rank_board([_player("carol", *floor), _player("Top", _char(0, 30)), _player("Bob", *floor),
                        _player("Last", _char(0, 12))])
    assert _order(board) == [(1, "Top"), (2, "Bob"), (2, "carol"), (4, "Last")]


def test_one_ranked_character_sits_below_two_of_the_same_rank():
    board = current_rank_board([_player("One", _char(0, 22)), _player("Two", _char(0, 22), _char(1, 0))])
    assert _order(board) == [(1, "Two"), (2, "One")]


def test_a_player_with_no_ranked_character_is_left_out():
    assert _order(current_rank_board([_player("Empty"), _player("Bob", _char(0, 20))])) == [(1, "Bob")]


# --- HTTP -----------------------------------------------------------------------

async def test_anyone_reads_the_board(client, use_server):
    await use_server(_server())
    response = client.get("/saves/leaderboard")
    assert response.status_code == 200
    assert response.json() == {"total": 2, "entries": [
        {"rank": 1, "username": "Alice", "saved_at": "2026-10-16T01:02:03Z", "account_rank": 20,
         "chars": PLAYERS[1]["chars"]},
        {"rank": 2, "username": "Bob", "saved_at": "2026-10-16T01:02:03Z", "account_rank": 20,
         "chars": PLAYERS[0]["chars"]},
    ]}


async def test_top_slices_the_board_and_total_counts_it_all(client, use_server):
    await use_server(_server())
    body = client.get("/saves/leaderboard", params={"top": 1}).json()
    assert (body["total"], _order(body["entries"])) == (2, [(1, "Alice")])


@pytest.mark.parametrize("top", [0, 1001])
def test_top_out_of_range_is_422(client, top):
    assert client.get("/saves/leaderboard", params={"top": top}).status_code == 422


async def test_an_unreachable_server_is_502(client, use_server):
    await use_server(_server(500, {"error": "internal_error", "message": "x"}))
    assert client.get("/saves/leaderboard").status_code == 502


# --- cache ----------------------------------------------------------------------

async def test_asks_the_server_once_whatever_the_top(client, use_server):
    seen = []
    await use_server(_server(seen=seen))
    for top in (1, 100, 1):
        assert client.get("/saves/leaderboard", params={"top": top}).status_code == 200
    assert len(seen) == 1


async def test_an_outage_is_not_remembered(client, use_server):
    seen = []
    await use_server(_server(500, {"error": "internal_error", "message": "x"}, seen=seen))
    for _ in range(2):
        assert client.get("/saves/leaderboard").status_code == 502
    assert len(seen) == 2


# --- days -----------------------------------------------------------------------

def _saved(npid: str, days_ago: float, *chars: dict) -> dict:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {**_player(npid, *chars), "saved_utc": when.strftime("%Y-%m-%d %H:%M:%S")}


RECENT = [
    _saved("Old", 40, _char(0, 30)),
    _saved("TiedA", 3, _char(0, 25)),
    _saved("TiedB", 29.9, _char(0, 25)),
    _saved("Low", 0, _char(0, 20)),
]


async def test_days_keeps_recent_players_and_ranks_them_among_themselves(client, use_server):
    await use_server(_server(body={"players": RECENT}))
    body = client.get("/saves/leaderboard", params={"days": 30}).json()
    assert body["total"] == 3
    assert _order(body["entries"]) == [(1, "TiedA"), (1, "TiedB"), (3, "Low")]


async def test_without_days_everyone_counts(client, use_server):
    await use_server(_server(body={"players": RECENT}))
    body = client.get("/saves/leaderboard").json()
    assert (body["total"], _order(body["entries"])[0]) == (4, (1, "Old"))


async def test_any_days_reads_the_one_cached_answer(client, use_server):
    seen = []
    await use_server(_server(body={"players": RECENT}, seen=seen))
    for params in ({}, {"days": 30}, {"days": 7}):
        assert client.get("/saves/leaderboard", params=params).status_code == 200
    assert len(seen) == 1


@pytest.mark.parametrize("days", [0, 366])
def test_days_out_of_range_is_422(client, days):
    assert client.get("/saves/leaderboard", params={"days": days}).status_code == 422
