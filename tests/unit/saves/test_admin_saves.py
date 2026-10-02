"""TTT2 save admin, with tag2now-save-admin's server replaced by an httpx mock transport."""

import json

import httpx
import pytest

from admin.exceptions import AccountNotFoundError, AdminPasswordError, NotAdminError
from saves import db
from saves.adapters.save_admin_server import SaveAdminServer
from saves.exceptions import (
    BackupNotFoundError, SaveConflictError, SaveNotFoundError, SaveRequestError, SavesUnavailableError,
)

# derive_rpcn_password("pw"), the value RPCS3 would send for it.
DERIVED_PW = "11E34BA86A98ED6A7DEBCA858864FAE02BC9C16AA4D99AAAB116311BDC6BFB01"
SHA = "a" * 64

CHAR = {"id": 0, "character": "Paul", "rank": 30, "rank_name": "Byakko", "tier": "빨강단",
        "points": 1234, "streak": -1, "wins": 10, "losses": 5}
SHOW = {
    "npid": "Alice", "user_id": 7, "data_id": 1001, "saved_utc": "2026-09-30 12:34:56.500000",
    "file": "/home/ec2-user/rpcn-data/tus_data/00000000000000001001.tdt", "sha256": SHA,
    "checksum_ok": True, "account_rank": 30, "progress": 4, "total": 15, "wins": 10, "losses": 5,
    "checksum": 123, "chars": [CHAR], "online": False,
}
SLOT_BEFORE = {"rank": 20, "rank_name": "Berserker", "points": 1500, "streak": 0}
SLOT_AFTER = {"rank": 29, "rank_name": "Genbu", "points": 1500, "streak": 0}
CHANGES = {"account_rank": None, "chars": [{"id": 0, "character": "Paul", "before": SLOT_BEFORE, "after": SLOT_AFTER}]}
WRITE = {"username": "Alice", "sha256": SHA, "online": False, "changes": CHANGES, "applied": True,
         "result": {"backup": "20261001-120000-123456", "checksum": "0x0A0B0C0D", "data_id": 1001, "landed": True}}
FLOOR = {**WRITE, "floor": {"reached": 30, "floor": 19, "raised": 1, "points_fixed": 0, "likely_demoted": False}}
LOG = {"records": [
    {"ts": "2026-10-01T12:00:00", "user": "root", "action": "set-rank", "npid": "Alice", "via": "web",
     "backup": "/home/ec2-user/backup/tdt/Alice/20261001-120000-123456.tdt", "rank": 29, "char": 0},
    {"ts": "2026-10-01T12:01:00", "user": "ec2-user", "action": "restore", "npid": "Alice",
     "source": "/home/ec2-user/backup/tdt/Alice/base.tdt", "backup": "/home/ec2-user/backup/tdt/Alice/x.tdt"},
]}
ANSWERS = {"show": SHOW, "backups": {"backups": [{"npid": "Alice", "label": "base", "total": 15, "account_rank": 30}]},
           "log": LOG, "floor": FLOOR}


def _server(status: int = 200, body: dict | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        action = request.url.path.removeprefix("/saves/")
        return httpx.Response(status, json=body if body is not None else ANSWERS.get(action, WRITE))
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


# --- adapter ------------------------------------------------------------------

async def test_sends_the_admins_derived_password_with_the_api_key():
    seen = []
    adapter = await _adapter(_server(seen=seen))

    answer = await adapter.call("set-rank", "root", "pw", {"username": "Alice", "char": 0, "rank": 29})

    request = seen[0]
    assert str(request.url) == "http://save-admin:8000/saves/set-rank"
    assert request.headers["X-API-Key"] == "key"
    assert json.loads(request.content) == {"username": "Alice", "char": 0, "rank": 29,
                                           "admin_username": "root", "admin_password": DERIVED_PW}
    assert answer == WRITE
    await adapter.close()


@pytest.mark.parametrize("status, code, error", [
    (401, "invalid_credentials", AdminPasswordError),
    (403, "forbidden", NotAdminError),
    (404, "user_not_found", AccountNotFoundError),
    (404, "save_not_found", SaveNotFoundError),
    (404, "backup_not_found", BackupNotFoundError),
    (400, "ambiguous_user", SaveRequestError),
    (400, "invalid_request", SaveRequestError),
    (409, "online", SaveConflictError),
    (409, "save_changed", SaveConflictError),
    (409, "likely_demoted", SaveConflictError),
    (503, "online_unknown", SavesUnavailableError),
    (502, "rpcn_unavailable", SavesUnavailableError),
    # faults between the two services, not the admin's to fix
    (403, "invalid_api_key", SavesUnavailableError),
    (404, "not_found", SavesUnavailableError),
    (500, "internal_error", SavesUnavailableError),
])
async def test_each_refusal_maps_to_its_own_error(status, code, error):
    adapter = await _adapter(_server(status, {"error": code, "message": "why"}))

    with pytest.raises(error):
        await adapter.call("show", "root", "pw", {"username": "Alice"})
    await adapter.close()


async def test_an_invalid_request_keeps_the_servers_reason():
    adapter = await _adapter(_server(400, {"error": "invalid_request", "message": "--rank must be 1..42"}))

    with pytest.raises(SaveRequestError, match="--rank must be 1..42"):
        await adapter.call("floor", "root", "pw", {"username": "Alice", "rank": 0})
    await adapter.close()


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="not json"),
    httpx.Response(200, json=["a list"]),
    httpx.Response(502, text="<html>bad gateway</html>"),
])
async def test_an_unreadable_answer_is_unavailable(response):
    adapter = await _adapter(httpx.MockTransport(lambda request: response))

    with pytest.raises(SavesUnavailableError):
        await adapter.call("show", "root", "pw", {"username": "Alice"})
    await adapter.close()


async def test_a_network_failure_is_unavailable():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    adapter = await _adapter(httpx.MockTransport(refuse))

    with pytest.raises(SavesUnavailableError):
        await adapter.call("show", "root", "pw", {"username": "Alice"})
    await adapter.close()


@pytest.mark.parametrize("url, api_key", [("", "key"), ("http://save-admin:8000", "")])
async def test_refuses_to_run_unconfigured(url, api_key):
    seen = []
    adapter = await _adapter(_server(seen=seen), url=url, api_key=api_key)

    with pytest.raises(SavesUnavailableError, match="설정되지 않았습니다"):
        await adapter.call("show", "root", "pw", {"username": "Alice"})
    assert seen == []
    await adapter.close()


# --- HTTP -----------------------------------------------------------------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)  # no `with`: lifespan stays off, the adapter is ours


@pytest.fixture
def as_admin(auth_headers):
    return auth_headers("root", admin=True)


BODY = {"username": "Alice", "password": "pw"}


async def test_show_answers_the_save_without_host_details(client, use_server, as_admin):
    await use_server(_server())

    response = client.post("/admin/saves/show", json=BODY, headers=as_admin)

    assert response.status_code == 200
    assert response.json() == {
        "username": "Alice", "data_id": 1001, "saved_at": "2026-09-30T12:34:56.500000Z", "sha256": SHA,
        "checksum_ok": True, "account_rank": 30, "progress": 4, "total": 15, "wins": 10, "losses": 5,
        "online": False, "chars": [CHAR],
    }


async def test_backups(client, use_server, as_admin):
    await use_server(_server())

    response = client.post("/admin/saves/backups", json=BODY, headers=as_admin)

    assert response.json() == {"backups": [{"label": "base", "total": 15, "account_rank": 30}]}


async def test_log_shows_backup_labels_not_host_paths(client, use_server, as_admin):
    seen = []
    await use_server(_server(seen=seen))

    response = client.post("/admin/saves/log", json={"password": "pw", "n": 20}, headers=as_admin)

    first, second = response.json()["records"]
    assert first == {"ts": "2026-10-01T12:00:00", "user": "root", "action": "set-rank", "username": "Alice",
                     "details": {"via": "web", "backup": "20261001-120000-123456", "rank": 29, "char": 0}}
    assert second["details"] == {"source": "base", "backup": "x"}
    assert json.loads(seen[0].content)["n"] == 20
    assert "username" not in json.loads(seen[0].content)


async def test_a_preview_forwards_dry_run_and_never_the_password(client, use_server, as_admin):
    seen = []
    await use_server(_server(body={**WRITE, "applied": False, "result": None}, seen=seen))

    response = client.post("/admin/saves/set-rank", json={**BODY, "char": 0, "rank": 29, "dry_run": True},
                           headers=as_admin)

    assert response.status_code == 200
    assert response.json()["applied"] is False
    sent = json.loads(seen[0].content)
    assert sent == {"username": "Alice", "char": 0, "rank": 29, "dry_run": True,
                    "admin_username": "root", "admin_password": DERIVED_PW}
    assert "password" not in sent


async def test_a_write_carries_the_previewed_sha256(client, use_server, as_admin):
    seen = []
    await use_server(_server(seen=seen))

    response = client.post("/admin/saves/set-rank", json={**BODY, "char": "all", "rank": 12, "expect_sha256": SHA},
                           headers=as_admin)

    assert response.status_code == 200
    assert response.json() == WRITE
    assert json.loads(seen[0].content)["expect_sha256"] == SHA


@pytest.mark.parametrize("path, extra", [
    ("/admin/saves/set-account-rank", {"rank": 30}),
    ("/admin/saves/restore", {"label": "base"}),
])
async def test_other_edits_answer_the_write(client, use_server, as_admin, path, extra):
    await use_server(_server())

    response = client.post(path, json={**BODY, **extra, "expect_sha256": SHA}, headers=as_admin)

    assert (response.status_code, response.json()) == (200, WRITE)


async def test_floor_answers_the_floor_it_used(client, use_server, as_admin):
    await use_server(_server())

    response = client.post("/admin/saves/floor", json={**BODY, "dry_run": True}, headers=as_admin)

    assert response.json()["floor"] == FLOOR["floor"]


@pytest.mark.parametrize("path, extra", [
    ("/admin/saves/set-rank", {"char": 59, "rank": 1}),
    ("/admin/saves/set-rank", {"char": "paul", "rank": 1}),
    ("/admin/saves/set-rank", {"char": 0, "rank": 43}),
    ("/admin/saves/set-rank", {"char": 0, "rank": 1, "points": 70000}),
    ("/admin/saves/set-rank", {"char": 0, "rank": 1, "expect_sha256": "not-a-hash"}),
    ("/admin/saves/floor", {"rank": 0}),
    ("/admin/saves/restore", {"label": "../Bob/base"}),
    ("/admin/saves/restore", {"label": "*"}),
])
async def test_bad_fields_never_reach_the_server(client, use_server, as_admin, path, extra):
    seen = []
    await use_server(_server(seen=seen))

    response = client.post(path, json={**BODY, **extra}, headers=as_admin)

    assert response.status_code == 422
    assert seen == []


async def test_an_online_player_is_409(client, use_server, as_admin):
    await use_server(_server(409, {"error": "online", "message": "Alice is online right now"}))

    response = client.post("/admin/saves/set-rank", json={**BODY, "char": 0, "rank": 29, "expect_sha256": SHA},
                           headers=as_admin)

    assert response.status_code == 409
    assert "접속 중" in response.json()["detail"]


async def test_a_wrong_admin_password_is_400_so_the_session_survives(client, use_server, as_admin):
    await use_server(_server(401, {"error": "invalid_credentials", "message": "wrong"}))

    response = client.post("/admin/saves/show", json=BODY, headers=as_admin)

    assert response.status_code == 400
    assert response.json()["detail"] == "비밀번호가 올바르지 않습니다."


@pytest.mark.parametrize("path", ["/admin/saves/show", "/admin/saves/floor"])
async def test_refuses_a_signed_in_non_admin_without_asking_the_server(client, use_server, auth_headers, path):
    seen = []
    await use_server(_server(seen=seen))

    response = client.post(path, json=BODY, headers=auth_headers("alice"))

    assert response.status_code == 403
    assert seen == []


def test_refuses_an_anonymous_caller(client):
    assert client.post("/admin/saves/show", json=BODY).status_code == 401
