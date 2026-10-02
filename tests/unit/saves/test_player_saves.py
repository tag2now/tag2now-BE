"""Anyone's TTT2 save, read-only, with tag2now-save-admin's server replaced by an httpx mock transport."""

import httpx
import pytest

from saves import db
from saves.adapters.save_admin_server import SaveAdminServer
from saves.exceptions import SavesUnavailableError
from shared.cache import DictCache

CHAR = {"id": 0, "character": "Paul", "rank": 30, "rank_name": "Byakko", "tier": "빨강단",
        "points": 1234, "streak": -1, "wins": 10, "losses": 5}
SAVE = {"npid": "Alice", "saved_utc": "2026-09-30 12:34:56.500000", "account_rank": 30,
        "total": 15, "wins": 10, "losses": 5, "chars": [CHAR]}


def _server(status: int = 200, body: dict | None = None, seen: list | None = None, applied: bool = True):
    """The save server: the profile read answers status/body, an admin edit of
    Alice's save answers a write, applied or only previewed."""
    write = {"username": "Alice", "sha256": "a" * 64, "online": False, "applied": applied,
             "changes": {"account_rank": None, "chars": []}, "result": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=write)
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=SAVE if body is None else body)
    return httpx.MockTransport(handler)


async def _adapter(transport, url="http://save-admin:8000", api_key="key") -> SaveAdminServer:
    adapter = SaveAdminServer(url, api_key, 1.0, transport=transport)
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
    monkeypatch.setattr("saves.service.cache_delete_pattern", fresh.delete_pattern)
    return fresh


# --- adapter ------------------------------------------------------------------

async def test_reads_with_a_get_and_the_api_key_only():
    seen = []
    adapter = await _adapter(_server(seen=seen))
    assert await adapter.read("Alice") == SAVE
    request = seen[0]
    assert (request.method, request.url.path, request.url.params["username"]) == ("GET", "/player/save", "Alice")
    assert request.headers["X-API-Key"] == "key"
    assert request.content == b""
    await adapter.close()


@pytest.mark.parametrize("code", ["user_not_found", "save_not_found"])
async def test_no_account_or_no_save_is_none(code):
    adapter = await _adapter(_server(404, {"error": code, "message": "x"}))
    assert await adapter.read("Alice") is None
    await adapter.close()


@pytest.mark.parametrize("response", [
    (403, {"error": "invalid_api_key", "message": "x"}),
    (500, {"error": "internal_error", "message": "x"}),
    (200, ["not", "an", "object"]),
])
async def test_anything_else_is_unavailable(response):
    adapter = await _adapter(_server(*response))
    with pytest.raises(SavesUnavailableError):
        await adapter.read("Alice")
    await adapter.close()


async def test_a_network_failure_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")
    adapter = await _adapter(httpx.MockTransport(handler))
    with pytest.raises(SavesUnavailableError):
        await adapter.read("Alice")
    await adapter.close()


@pytest.mark.parametrize("url, api_key", [("", "key"), ("http://save-admin:8000", "")])
async def test_refuses_to_run_unconfigured(url, api_key):
    seen = []
    adapter = await _adapter(_server(seen=seen), url=url, api_key=api_key)
    with pytest.raises(SavesUnavailableError):
        await adapter.read("Alice")
    assert seen == []
    await adapter.close()


# --- HTTP -----------------------------------------------------------------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)  # no `with`: lifespan stays off, the adapter is ours


async def test_anyone_reads_a_players_ranks(client, use_server):
    await use_server(_server())
    response = client.get("/saves/players/Alice")
    assert response.status_code == 200
    assert response.json() == {
        "username": "Alice", "saved_at": "2026-09-30T12:34:56.500000Z", "account_rank": 30,
        "total": 15, "wins": 10, "losses": 5, "chars": [CHAR],
    }


async def test_no_save_is_404(client, use_server):
    await use_server(_server(404, {"error": "save_not_found", "message": "x"}))
    response = client.get("/saves/players/Bob")
    assert response.status_code == 404
    assert response.json()["detail"] == "이 플레이어의 TTT2 세이브가 없습니다."


async def test_an_unreachable_server_is_502(client, use_server):
    await use_server(_server(500, {"error": "internal_error", "message": "x"}))
    assert client.get("/saves/players/Alice").status_code == 502


# --- cache ----------------------------------------------------------------------

async def test_asks_the_server_once_per_player_whatever_the_case(client, use_server):
    seen = []
    await use_server(_server(seen=seen))
    for name in ("Alice", "alice", "ALICE"):
        assert client.get(f"/saves/players/{name}").status_code == 200
    assert len(seen) == 1


async def test_a_missing_save_is_remembered_too(client, use_server):
    seen = []
    await use_server(_server(404, {"error": "save_not_found", "message": "x"}, seen=seen))
    for _ in range(2):
        assert client.get("/saves/players/Bob").status_code == 404
    assert len(seen) == 1


async def test_an_outage_is_not_remembered(client, use_server):
    seen = []
    await use_server(_server(500, {"error": "internal_error", "message": "x"}, seen=seen))
    for _ in range(2):
        assert client.get("/saves/players/Alice").status_code == 502
    assert len(seen) == 2


@pytest.mark.parametrize("applied, reads", [(True, 2), (False, 1)])
async def test_a_written_edit_shows_at_once_and_a_preview_changes_nothing(
        client, use_server, auth_headers, applied, reads):
    seen = []
    await use_server(_server(seen=seen, applied=applied))
    client.get("/saves/players/alice")

    body = {"username": "ALICE", "password": "pw", "rank": 29, **({"expect_sha256": "a" * 64} if applied else {"dry_run": True})}
    response = client.post("/admin/saves/set-account-rank", json=body, headers=auth_headers("root", admin=True))
    assert response.status_code == 200

    client.get("/saves/players/alice")
    assert len(seen) == reads
