"""Login and token handling, with RPCN replaced by an httpx mock transport."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from auth import db, service, tokens
from auth.adapters.rpcn_stat import RpcnStatAccountVerifier
from auth.exceptions import AccountBannedError, AuthUnavailableError, InvalidCredentialsError, InvalidTokenError
from auth.models import AuthUser
from shared.settings import get_settings

ACCOUNT = {"user_id": 7, "username": "Alice", "online_name": "앨리스", "avatar_url": "https://a/x.png", "admin": False, "banned": False}


def _rpcn(status: int = 200, body: dict | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else ACCOUNT)
    return httpx.MockTransport(handler)


async def _verifier(transport, base_url="http://rpcn/rpcn_stats", api_key="key") -> RpcnStatAccountVerifier:
    verifier = RpcnStatAccountVerifier(base_url, api_key, 1.0, transport=transport)
    await verifier.init()
    return verifier


@pytest.fixture
async def use_verifier():
    """Install a verifier for the service, and restore whatever was there."""
    previous = db._verifier
    installed = []

    async def install(transport, **kwargs):
        verifier = await _verifier(transport, **kwargs)
        installed.append(verifier)
        db.set_verifier(verifier)
        return verifier

    yield install
    for verifier in installed:
        await verifier.close()
    db.set_verifier(previous)


# --- RPCN adapter -----------------------------------------------------------

async def test_verify_posts_the_credentials_with_the_api_key():
    seen = []
    verifier = await _verifier(_rpcn(seen=seen))

    account = await verifier.verify("alice", "pw")

    request = seen[0]
    assert str(request.url) == "http://rpcn/rpcn_stats/external/users/verify"
    assert request.headers["X-API-Key"] == "key"
    assert json.loads(request.content) == {"username": "alice", "password": "pw"}
    assert account.username == "Alice"  # RPCN's spelling, not the typed one
    await verifier.close()


async def test_verify_maps_401_to_invalid_credentials():
    verifier = await _verifier(_rpcn(401, {"error": "invalid_credentials"}))

    with pytest.raises(InvalidCredentialsError):
        await verifier.verify("alice", "wrong")
    await verifier.close()


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_verify_treats_every_other_status_as_our_outage(status):
    """A wrong API key is a deployment fault; the user must not read it as a bad password."""
    verifier = await _verifier(_rpcn(status, {"error": "x"}))

    with pytest.raises(AuthUnavailableError):
        await verifier.verify("alice", "pw")
    await verifier.close()


async def test_verify_maps_a_network_failure_to_unavailable():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    verifier = await _verifier(httpx.MockTransport(refuse))

    with pytest.raises(AuthUnavailableError):
        await verifier.verify("alice", "pw")
    await verifier.close()


async def test_verify_refuses_to_run_unconfigured():
    verifier = await _verifier(_rpcn(), api_key="")

    with pytest.raises(AuthUnavailableError):
        await verifier.verify("alice", "pw")
    await verifier.close()


# --- Tokens -----------------------------------------------------------------

def test_a_token_round_trips_the_user():
    user = AuthUser(username="Alice", online_name="앨리스", avatar_url="u", admin=True)

    token, expires_in = tokens.issue_token(user)

    assert tokens.read_token(token) == user
    assert expires_in == get_settings().jwt_ttl_seconds


def test_an_expired_token_is_refused():
    long_ago = datetime.now(timezone.utc) - timedelta(seconds=get_settings().jwt_ttl_seconds + 60)
    token, _ = tokens.issue_token(AuthUser(username="a", online_name="a"), now=long_ago)

    with pytest.raises(InvalidTokenError, match="만료"):
        tokens.read_token(token)


def test_a_tampered_token_is_refused():
    token, _ = tokens.issue_token(AuthUser(username="alice", online_name="a"))
    header, payload, signature = token.split(".")
    forged = ".".join([header, payload, signature[:-2] + ("AA" if signature[-2:] != "AA" else "BB")])

    with pytest.raises(InvalidTokenError):
        tokens.read_token(forged)


def test_a_token_signed_with_another_key_is_refused():
    import jwt
    now = datetime.now(timezone.utc)
    foreign = jwt.encode({"iss": "tag2now", "sub": "alice", "iat": now, "exp": now + timedelta(hours=1)}, "x" * 32, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        tokens.read_token(foreign)


def test_an_unsigned_token_is_refused():
    import jwt
    now = datetime.now(timezone.utc)
    unsigned = jwt.encode({"iss": "tag2now", "sub": "alice", "iat": now, "exp": now + timedelta(hours=1)}, None, algorithm="none")

    with pytest.raises(InvalidTokenError):
        tokens.read_token(unsigned)


def test_a_short_secret_disables_signing(monkeypatch):
    from pydantic import SecretStr
    monkeypatch.setattr(get_settings(), "jwt_secret", SecretStr("short"))

    with pytest.raises(AuthUnavailableError):
        tokens.issue_token(AuthUser(username="a", online_name="a"))


# --- Service ----------------------------------------------------------------

async def test_login_issues_a_token_for_the_canonical_username(use_verifier):
    await use_verifier(_rpcn())

    token, _, user = await service.login("alice", "pw")

    assert user.username == "Alice"
    assert user.online_name == "앨리스"
    assert service.authenticate(token) == user


async def test_login_refuses_a_banned_account(use_verifier):
    await use_verifier(_rpcn(body={**ACCOUNT, "banned": True}))

    with pytest.raises(AccountBannedError):
        await service.login("alice", "pw")


async def test_login_falls_back_to_the_username_when_there_is_no_online_name(use_verifier):
    await use_verifier(_rpcn(body={**ACCOUNT, "online_name": ""}))

    _, _, user = await service.login("alice", "pw")

    assert user.online_name == "Alice"


# --- HTTP -------------------------------------------------------------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)  # no `with`: lifespan stays off, the verifier is ours


async def test_login_route_returns_a_bearer_token_that_me_accepts(client, use_verifier):
    await use_verifier(_rpcn())

    login = client.post("/auth/login", json={"username": "alice", "password": "pw"})

    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().jwt_ttl_seconds
    assert body["user"] == {"username": "Alice", "online_name": "앨리스", "avatar_url": "https://a/x.png", "admin": False}

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "Alice"


@pytest.mark.parametrize("status, body, expected", [
    (401, {"error": "invalid_credentials"}, 401),
    (200, {**ACCOUNT, "banned": True}, 403),
    (403, {"error": "forbidden"}, 502),
])
async def test_login_route_maps_each_rpcn_answer(client, use_verifier, status, body, expected):
    await use_verifier(_rpcn(status, body))

    response = client.post("/auth/login", json={"username": "alice", "password": "pw"})

    assert response.status_code == expected


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic YWxpY2U6cHc="}])
def test_me_refuses_anything_but_a_valid_bearer_token(client, headers):
    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
