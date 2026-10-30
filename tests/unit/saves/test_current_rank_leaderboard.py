"""The current-rank leaderboard, with tag2now-save-admin's server replaced by an httpx mock transport."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS
from saves.adapters.save_admin_server import SaveAdminServer
from saves.exceptions import SavesUnavailableError
from saves.service import SavesService, current_rank_board
from shared.cache import DictCache


def _char(id: int, rank: int, points: int = 0, wins: int = 1) -> dict:
    return {
        "id": id,
        "character": f"C{id}",
        "rank": rank,
        "rank_name": f"R{rank}",
        "tier": "t",
        "points": points,
        "streak": 0,
        "wins": wins,
        "losses": 0,
    }


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
async def use_server(installed):
    """Give the routes a service over an adapter talking to `transport`."""
    adapters = []

    async def install(transport):
        adapter = await _adapter(transport)
        adapters.append(adapter)
        installed["service"] = SavesService(adapter)
        return adapter

    yield install
    for adapter in adapters:
        await adapter.close()


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
    assert await adapter.read_ranks() == PLAYERS
    request = seen[0]
    assert (request.method, request.url.path) == ("GET", "/players/top-ranks")
    assert request.headers["X-API-Key"] == "key"
    await adapter.close()


@pytest.mark.parametrize(
    "response",
    [
        (403, {"error": "invalid_api_key", "message": "x"}),
        (500, {"error": "internal_error", "message": "x"}),
    ],
)
async def test_a_refusal_is_unavailable(response):
    adapter = await _adapter(_server(*response))
    with pytest.raises(SavesUnavailableError):
        await adapter.read_ranks()
    await adapter.close()


# --- ordering -------------------------------------------------------------------


def test_best_character_first_then_the_second():
    board = current_rank_board(
        [
            _player("Low", _char(0, 21), _char(1, 21)),
            _player("Top", _char(0, 25), _char(1, 12)),
            _player("Pair", _char(0, 22), _char(1, 22)),
            _player("Second", _char(0, 22), _char(1, 14)),
        ]
    )
    assert _order(board) == [(1, "Top"), (2, "Pair"), (3, "Second"), (4, "Low")]


def test_points_break_a_tie_of_ranks():
    board = current_rank_board(
        [
            _player("A", _char(0, 22, 100), _char(1, 20, 9000)),
            _player("B", _char(0, 22, 4000), _char(1, 20, 0)),
            _player("C", _char(0, 22, 100), _char(1, 20, 9001)),
        ]
    )
    assert _order(board) == [(1, "B"), (2, "C"), (3, "A")]


def test_equal_standings_share_a_place_and_list_by_name():
    floor = (_char(0, 14, 5000), _char(1, 14, 5000))
    board = current_rank_board(
        [_player("carol", *floor), _player("Top", _char(0, 30)), _player("Bob", *floor), _player("Last", _char(0, 12))]
    )
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
    assert response.json() == {
        "total": 2,
        "entries": [
            {
                "rank": 1,
                "username": "Alice",
                "saved_at": "2026-10-16T01:02:03Z",
                "account_rank": 20,
                "chars": PLAYERS[1]["chars"],
            },
            {
                "rank": 2,
                "username": "Bob",
                "saved_at": "2026-10-16T01:02:03Z",
                "account_rank": 20,
                "chars": PLAYERS[0]["chars"],
            },
        ],
    }


async def test_the_best_two_of_every_character_rank_and_show_on_the_board(client, use_server):
    # save-admin answers every character, in slot order
    alice = _player("Alice", _char(1, 12), _char(2, 25, 100), _char(3, 25, 4000), _char(4, 20))
    bob = _player("Bob", _char(0, 25, 5000), _char(1, 11))
    await use_server(_server(body={"players": [bob, alice]}))
    entries = client.get("/saves/leaderboard").json()["entries"]
    assert _order(entries) == [(1, "Alice"), (2, "Bob")]
    assert entries[0]["chars"] == [_char(3, 25, 4000), _char(2, 25, 100)]


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


# --- excluded accounts -----------------------------------------------------------


async def test_excluded_accounts_are_left_off_and_the_rest_ranked_without_them(client, use_server, monkeypatch):
    from shared.settings import get_settings

    monkeypatch.setattr(get_settings(), "ranking_excluded_npids", ["alice"])
    await use_server(_server())
    body = client.get("/saves/leaderboard").json()
    assert (body["total"], _order(body["entries"])) == (1, [(1, "Bob")])


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


# --- current-rank holders -----------------------------------------------------------


def _unplayed(id: int, rank: int = 10) -> dict:
    """A character the floor raised and no one has played."""
    return _char(id, rank, wins=0)


def _holders(client, **params):
    return client.get("/saves/current-rank-holders", params=params)


def _names(body: dict) -> list[str]:
    return [e["username"] for e in body["entries"]]


async def test_a_character_below_the_best_two_is_found_alone(client, use_server):
    alice = _saved("Alice", 1, _char(0, 25), _char(1, 24), _char(2, 12), _char(5, 12))
    await use_server(_server(body={"players": [alice]}))
    response = _holders(client, rank=12)
    assert response.status_code == 200
    body = response.json()
    assert (body["rank"], body["rank_name"], body["total"]) == (12, TEKKEN_RANKS[12]["name"], 1)
    entry = body["entries"][0]
    assert (entry["username"], entry["account_rank"]) == ("Alice", 20)
    assert entry["chars"] == [{"id": 2, "character": TTT2_CHARACTERS[2]}, {"id": 5, "character": TTT2_CHARACTERS[5]}]


async def test_an_unplayed_character_holds_no_rank_but_its_player_stays_on_the_board(client, use_server):
    floored = _saved("Floored", 1, _unplayed(0), _unplayed(1))
    played = _saved("Played", 1, _unplayed(0), _char(1, 10))
    await use_server(_server(body={"players": [floored, played]}))
    assert _names(_holders(client, rank=10).json()) == ["Played"]
    assert sorted(e["username"] for e in client.get("/saves/leaderboard").json()["entries"]) == ["Floored", "Played"]


async def test_the_lowest_on_the_leaderboard_comes_first_then_by_name(client, use_server):
    await use_server(
        _server(
            body={
                "players": [
                    _saved("Strong", 1, _char(0, 30), _char(1, 14)),
                    _saved("lowb", 1, _char(0, 14)),
                    _saved("Mid", 1, _char(0, 20), _char(1, 14)),
                    _saved("LowA", 1, _char(0, 14)),
                ]
            }
        )
    )
    assert _names(_holders(client, rank=14).json()) == ["LowA", "lowb", "Mid", "Strong"]


async def test_without_days_only_the_last_30_count(client, use_server):
    await use_server(
        _server(
            body={
                "players": [
                    _saved("Today", 0, _char(0, 15)),
                    _saved("Recent", 29.9, _char(0, 15)),
                    _saved("Gone", 30.1, _char(0, 15)),
                ]
            }
        )
    )
    assert sorted(_names(_holders(client, rank=15).json())) == ["Recent", "Today"]
    assert _names(_holders(client, rank=15, days=7).json()) == ["Today"]


async def test_holders_top_slices_and_total_counts_them_all(client, use_server):
    await use_server(_server(body={"players": [_saved(n, 1, _char(0, 15)) for n in ("A", "B", "C")]}))
    body = _holders(client, rank=15, top=2).json()
    assert (body["total"], _names(body)) == (3, ["A", "B"])


async def test_excluded_accounts_hold_nothing(client, use_server, monkeypatch):
    from shared.settings import get_settings

    monkeypatch.setattr(get_settings(), "ranking_excluded_npids", ["alice"])
    await use_server(_server(body={"players": [_saved("Alice", 1, _char(0, 15)), _saved("Bob", 1, _char(0, 15))]}))
    assert _names(_holders(client, rank=15).json()) == ["Bob"]


async def test_one_read_serves_the_board_and_every_rank_an_empty_one_too(client, use_server):
    seen = []
    await use_server(_server(body={"players": [_saved("Alice", 1, _char(0, 15))]}, seen=seen))
    assert client.get("/saves/leaderboard").status_code == 200
    assert _holders(client, rank=15).json()["total"] == 1
    for _ in range(2):
        assert _holders(client, rank=40).json()["total"] == 0
    assert len(seen) == 1


async def test_holders_ask_the_server_when_nothing_is_cached(client, use_server):
    seen = []
    await use_server(_server(body={"players": [_saved("Alice", 1, _char(0, 15))]}, seen=seen))
    assert _names(_holders(client, rank=15).json()) == ["Alice"]
    assert client.get("/saves/leaderboard").json()["total"] == 1
    assert len(seen) == 1


async def test_holders_outage_is_502_and_not_remembered(client, use_server):
    seen = []
    await use_server(_server(500, {"error": "internal_error", "message": "x"}, seen=seen))
    for _ in range(2):
        assert _holders(client, rank=15).status_code == 502
    assert len(seen) == 2


@pytest.mark.parametrize(
    "params",
    [
        {"rank": 9},
        {"rank": 43},
        {},
        {"rank": 10, "top": 0},
        {"rank": 10, "top": 1001},
        {"rank": 10, "days": 0},
        {"rank": 10, "days": 366},
    ],
)
def test_holders_params_out_of_range_are_422(client, params):
    assert _holders(client, **params).status_code == 422


async def test_first_dan_is_the_lowest_rank_asked(client, use_server):
    await use_server(_server(body={"players": [_saved("Alice", 1, _char(0, 10))]}))
    assert _names(_holders(client, rank=10).json()) == ["Alice"]
