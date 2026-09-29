"""Account moderation, with rpcn-narco replaced by an httpx mock transport."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from admin import db
from admin.adapters.rpcn_api_server import RpcnApiServerAccountAdmin
from admin.exceptions import AccountNotFoundError, AdminPasswordError, AdminUnavailableError, NotAdminError

INFO = {
    "user_id": 7, "username": "Alice", "online_name": "앨리스", "avatar_url": "https://a/x.png",
    "admin": False, "banned": False, "online": True, "creation": 1_700_000_000, "last_login": None,
}
BANNED = {"user_id": 7, "username": "Alice", "banned": True, "kicked": True}
# derive_rpcn_password("pw"), the value RPCS3 would send for it.
DERIVED_PW = "11E34BA86A98ED6A7DEBCA858864FAE02BC9C16AA4D99AAAB116311BDC6BFB01"


def _rpcn(status: int = 200, body: dict | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        default = BANNED if request.url.path.endswith("/ban") else INFO
        return httpx.Response(status, json=body if body is not None else default)
    return httpx.MockTransport(handler)


async def _adapter(transport, api_key="key") -> RpcnApiServerAccountAdmin:
    adapter = RpcnApiServerAccountAdmin("http://rpcn:31315", api_key, 1.0, transport=transport)
    await adapter.init()
    return adapter


@pytest.fixture
async def use_rpcn():
    """Install an adapter for the service, and restore whatever was there."""
    previous = db._admin
    installed = []

    async def install(transport):
        adapter = await _adapter(transport)
        installed.append(adapter)
        db.set_account_admin(adapter)
        return adapter

    yield install
    for adapter in installed:
        await adapter.close()
    db.set_account_admin(previous)


# --- RPCN adapter -----------------------------------------------------------

async def test_ban_sends_the_admins_derived_password_with_the_api_key():
    seen = []
    adapter = await _adapter(_rpcn(seen=seen))

    result = await adapter.ban("root", "pw", "Alice")

    request = seen[0]
    assert str(request.url) == "http://rpcn:31315/admin/users/ban"
    assert request.headers["X-API-Key"] == "key"
    assert json.loads(request.content) == {"admin_username": "root", "admin_password": DERIVED_PW, "username": "Alice"}
    assert result.username == "Alice"
    assert result.kicked is True
    await adapter.close()


async def test_lookup_reads_rpcn_timestamps_as_utc_and_keeps_a_missing_one_empty():
    adapter = await _adapter(_rpcn())

    status = await adapter.lookup("root", "pw", "Alice")

    assert status.online is True
    assert status.created_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert status.last_login_at is None
    await adapter.close()


@pytest.mark.parametrize("status, body, error", [
    (401, {"error": "invalid_credentials"}, AdminPasswordError),
    (403, {"error": "forbidden"}, NotAdminError),
    (404, {"error": "user_not_found"}, AccountNotFoundError),
    (404, None, AdminUnavailableError),  # API switched off: a bare 404
    (400, {"error": "invalid_request"}, AdminUnavailableError),
    (500, {"error": "internal_error"}, AdminUnavailableError),
])
async def test_each_rpcn_refusal_maps_to_its_own_error(status, body, error):
    def handler(request):
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    adapter = await _adapter(httpx.MockTransport(handler))

    with pytest.raises(error):
        await adapter.ban("root", "pw", "Alice")
    await adapter.close()


async def test_a_network_failure_is_unavailable():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    adapter = await _adapter(httpx.MockTransport(refuse))

    with pytest.raises(AdminUnavailableError):
        await adapter.lookup("root", "pw", "Alice")
    await adapter.close()


async def test_an_unexpected_body_is_unavailable():
    adapter = await _adapter(_rpcn(body={"username": "Alice"}))

    with pytest.raises(AdminUnavailableError):
        await adapter.lookup("root", "pw", "Alice")
    await adapter.close()


async def test_refuses_to_run_unconfigured():
    seen = []
    adapter = await _adapter(_rpcn(seen=seen), api_key="")

    with pytest.raises(AdminUnavailableError):
        await adapter.ban("root", "pw", "Alice")
    assert seen == []
    await adapter.close()


# --- HTTP -------------------------------------------------------------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)  # no `with`: lifespan stays off, the adapter is ours


BODY = {"username": "Alice", "password": "pw"}


async def test_lookup_route_returns_the_accounts_standing(client, use_rpcn, auth_headers):
    await use_rpcn(_rpcn())

    response = client.post("/admin/users/lookup", json=BODY, headers=auth_headers("root", admin=True))

    assert response.status_code == 200
    assert response.json() == {
        "username": "Alice", "online_name": "앨리스", "avatar_url": "https://a/x.png",
        "admin": False, "banned": False, "online": True,
        "created_at": "2023-11-14T22:13:20Z", "last_login_at": None,
    }


async def test_ban_route_acts_as_the_signed_in_admin(client, use_rpcn, auth_headers):
    seen = []
    await use_rpcn(_rpcn(seen=seen))

    response = client.post("/admin/users/ban", json=BODY, headers=auth_headers("root", admin=True))

    assert response.status_code == 200
    assert response.json() == {"username": "Alice", "banned": True, "kicked": True}
    assert json.loads(seen[0].content)["admin_username"] == "root"


@pytest.mark.parametrize("path", ["/admin/users/lookup", "/admin/users/ban"])
async def test_admin_routes_refuse_a_signed_in_non_admin_without_asking_rpcn(client, use_rpcn, auth_headers, path):
    seen = []
    await use_rpcn(_rpcn(seen=seen))

    response = client.post(path, json=BODY, headers=auth_headers("alice"))

    assert response.status_code == 403
    assert seen == []


@pytest.mark.parametrize("path", ["/admin/users/lookup", "/admin/users/ban"])
def test_admin_routes_refuse_an_anonymous_caller(client, path):
    response = client.post(path, json=BODY)

    assert response.status_code == 401


async def test_a_wrong_admin_password_is_400_so_the_session_survives(client, use_rpcn, auth_headers):
    """A 401 on a signed-in request signs the user out in the frontend."""
    await use_rpcn(_rpcn(401, {"error": "invalid_credentials"}))

    response = client.post("/admin/users/ban", json=BODY, headers=auth_headers("root", admin=True))

    assert response.status_code == 400
    assert response.json()["detail"] == "비밀번호가 올바르지 않습니다."


@pytest.mark.parametrize("target", ["root", "ROOT"])
async def test_an_admin_cannot_ban_their_own_account(client, use_rpcn, auth_headers, target):
    seen = []
    await use_rpcn(_rpcn(seen=seen))

    response = client.post("/admin/users/ban", json={**BODY, "username": target}, headers=auth_headers("root", admin=True))

    assert response.status_code == 400
    assert seen == []


async def test_an_unknown_target_is_404(client, use_rpcn, auth_headers):
    await use_rpcn(_rpcn(404, {"error": "user_not_found"}))

    response = client.post("/admin/users/lookup", json=BODY, headers=auth_headers("root", admin=True))

    assert response.status_code == 404
