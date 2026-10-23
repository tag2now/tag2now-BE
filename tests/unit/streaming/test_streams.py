"""Registering a channel and finding who is live, over an in-memory repository and a fake platform."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from shared.cache import DictCache
from streaming.service import StreamingService
from streaming.exceptions import ChannelTakenError, StreamingUnavailableError
from streaming.models import LiveBroadcast, PlatformChannel, StreamChannel
from streaming.ports import StreamChannelRepository, StreamPlatform

ALICE_CH = "a" * 32
BOB_CH = "b" * 32
CAROL_CH = "c" * 32


class MemoryRepository(StreamChannelRepository):
    def __init__(self):
        self.rows: dict[tuple[str, str], StreamChannel] = {}
        self.listed = 0

    async def get(self, session, username, platform):
        return self.rows.get((username, platform))

    async def list_all(self, session):
        self.listed += 1
        return list(self.rows.values())

    async def upsert(self, session, username, platform, channel):
        if any(c.channel_id == channel.channel_id and c.username != username for c in self.rows.values()):
            raise ChannelTakenError("이미 다른 계정에 연결된 채널입니다.")
        row = StreamChannel(username, platform, channel.channel_id, channel.channel_name,
                            datetime(2026, 10, 3, tzinfo=timezone.utc))
        self.rows[(username, platform)] = row
        return row

    async def delete(self, session, username, platform):
        key = next((k for k in self.rows if k[0].lower() == username.lower() and k[1] == platform), None)
        return self.rows.pop(key, None) is not None


class FakePlatform(StreamPlatform):
    def __init__(self, channels=(), live=None, failing=()):
        self.channels = {c: f"{c[:4]} 채널" for c in channels}
        self.on_air = live or {}
        self.failing = set(failing)
        self.checked: list[str] = []

    async def init(self): ...

    async def close(self): ...

    async def channel(self, channel_id):
        name = self.channels.get(channel_id)
        return PlatformChannel(channel_id, name) if name else None

    async def live(self, channel_id):
        self.checked.append(channel_id)
        if channel_id in self.failing:
            raise StreamingUnavailableError("x")
        return self.on_air.get(channel_id)


@pytest.fixture
def sessions():
    """A session factory whose sessions the in-memory repository ignores."""
    session = AsyncMock()

    @asynccontextmanager
    async def begin():
        yield

    session.begin = begin

    @asynccontextmanager
    async def open_session():
        yield session

    return open_session


@pytest.fixture(autouse=True)
def cache(monkeypatch):
    fresh = DictCache()
    monkeypatch.setattr("streaming.service.cache_get", fresh.get)
    monkeypatch.setattr("streaming.service.cache_set", fresh.set)
    monkeypatch.setattr("streaming.service.cache_delete", fresh.delete)
    return fresh


@pytest.fixture
def repo():
    return MemoryRepository()


@pytest.fixture
def use_platform(installed, repo, sessions):
    """Give the routes, and `installed["service"]`, a service over `repo` and this platform."""

    def install(platform: StreamPlatform) -> StreamPlatform:
        installed["service"] = StreamingService(repo, platform, sessions)
        return platform

    return install


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)  # no `with`: lifespan stays off, the adapters are ours


async def _register(repo, username, channel_id):
    await repo.upsert(None, username, "chzzk", PlatformChannel(channel_id, f"{username} 채널"))


# --- live -----------------------------------------------------------------------

async def test_answers_only_the_registered_players_asked_about_who_are_on_air(repo, use_platform, installed):
    for username, channel in (("Alice", ALICE_CH), ("bob", BOB_CH), ("carol", CAROL_CH)):
        await _register(repo, username, channel)
    platform = use_platform(FakePlatform(live={ALICE_CH: LiveBroadcast("TTT2 랭크전", 42, "TTT2"),
                                               CAROL_CH: LiveBroadcast("밖에서 방송", 9, "talk")}))

    live = await installed["service"].live_for({"alice", "bob", "dave"})

    assert live == {"alice": {"platform": "chzzk", "channel_name": "Alice 채널",
                              "url": f"https://chzzk.naver.com/live/{ALICE_CH}",
                              "title": "TTT2 랭크전", "viewer_count": 42}}
    # carol is on air but was not asked about, so her channel is never checked.
    assert sorted(platform.checked) == [ALICE_CH, BOB_CH]


async def test_one_failing_channel_does_not_hide_the_others(repo, use_platform, installed):
    await _register(repo, "alice", ALICE_CH)
    await _register(repo, "bob", BOB_CH)
    use_platform(FakePlatform(live={BOB_CH: LiveBroadcast("방송", 1, "")}, failing={ALICE_CH}))

    assert list(await installed["service"].live_for({"alice", "bob"})) == ["bob"]


@pytest.mark.parametrize("live, failing", [({ALICE_CH: LiveBroadcast("방송", 1, "")}, ()), ({}, ()), ({}, {ALICE_CH})])
async def test_asks_about_a_channel_once_until_its_cache_expires(repo, use_platform, live, failing, installed):
    await _register(repo, "alice", ALICE_CH)
    platform = use_platform(FakePlatform(live=live, failing=failing))

    for _ in range(3):
        await installed["service"].live_for({"alice"})

    assert platform.checked == [ALICE_CH]
    assert repo.listed == 1


async def test_nobody_asked_reads_nothing(repo, use_platform, installed):
    await _register(repo, "alice", ALICE_CH)
    platform = use_platform(FakePlatform())

    assert await installed["service"].live_for(set()) == {}
    assert (platform.checked, repo.listed) == ([], 0)


# --- own channel ----------------------------------------------------------------

async def test_registers_a_pasted_url_under_the_signed_in_account(client, repo, use_platform, auth_headers):
    use_platform(FakePlatform(channels=[ALICE_CH]))
    headers = auth_headers("alice")

    response = client.put("/streams/me", json={"channel": f"https://chzzk.naver.com/live/{ALICE_CH}"}, headers=headers)

    assert response.status_code == 200
    channel = response.json()["channel"]
    assert (channel["channel_id"], channel["channel_name"]) == (ALICE_CH, "aaaa 채널")
    assert channel["channel_url"] == f"https://chzzk.naver.com/live/{ALICE_CH}"
    assert client.get("/streams/me", headers=headers).json()["channel"]["channel_id"] == ALICE_CH


async def test_no_channel_reads_as_null(client, repo, use_platform, auth_headers):
    use_platform(FakePlatform())
    assert client.get("/streams/me", headers=auth_headers("alice")).json() == {"channel": None}


@pytest.mark.parametrize("text, detail", [
    ("내 방송", "치지직 채널 주소를 확인해 주세요. 예: https://chzzk.naver.com/채널ID"),
    (BOB_CH, "치지직에서 찾을 수 없는 채널입니다."),
])
async def test_refuses_what_names_no_real_channel(client, repo, use_platform, auth_headers, text, detail):
    use_platform(FakePlatform(channels=[ALICE_CH]))
    response = client.put("/streams/me", json={"channel": text}, headers=auth_headers("alice"))
    assert (response.status_code, response.json()["detail"]) == (400, detail)
    assert repo.rows == {}


async def test_a_channel_belongs_to_one_account(client, repo, use_platform, auth_headers):
    use_platform(FakePlatform(channels=[ALICE_CH]))
    await _register(repo, "alice", ALICE_CH)

    response = client.put("/streams/me", json={"channel": ALICE_CH}, headers=auth_headers("mallory"))

    assert response.status_code == 409
    assert repo.rows[("alice", "chzzk")].channel_id == ALICE_CH


async def test_a_new_registration_shows_without_waiting_for_the_cache(client, repo, use_platform, auth_headers, installed):
    use_platform(FakePlatform(channels=[ALICE_CH], live={ALICE_CH: LiveBroadcast("방송", 1, "")}))
    assert await installed["service"].live_for({"alice"}) == {}

    client.put("/streams/me", json={"channel": ALICE_CH}, headers=auth_headers("alice"))

    assert list(await installed["service"].live_for({"alice"})) == ["alice"]


async def test_disconnecting_succeeds_with_or_without_a_channel(client, repo, use_platform, auth_headers):
    use_platform(FakePlatform())
    await _register(repo, "alice", ALICE_CH)
    headers = auth_headers("alice")

    assert client.delete("/streams/me", headers=headers).status_code == 204
    assert client.delete("/streams/me", headers=headers).status_code == 204
    assert repo.rows == {}


@pytest.mark.parametrize("method, path", [("get", "/streams/me"), ("put", "/streams/me"), ("delete", "/streams/me")])
def test_own_channel_routes_need_a_login(client, method, path):
    assert client.request(method, path, json={"channel": ALICE_CH}).status_code == 401


# --- admin ----------------------------------------------------------------------

async def test_an_admin_lists_and_removes_whatever_the_case(client, repo, use_platform, auth_headers):
    use_platform(FakePlatform())
    await _register(repo, "Alice", ALICE_CH)
    headers = auth_headers("root", admin=True)

    listed = client.get("/admin/streams", headers=headers).json()["channels"]
    assert [(c["username"], c["channel_id"]) for c in listed] == [("Alice", ALICE_CH)]

    assert client.delete("/admin/streams/alice", headers=headers).status_code == 204
    assert repo.rows == {}
    assert client.delete("/admin/streams/alice", headers=headers).status_code == 404


async def test_admin_routes_refuse_everyone_else(client, repo, auth_headers):
    headers = auth_headers("alice")
    assert client.get("/admin/streams", headers=headers).status_code == 403
    assert client.delete("/admin/streams/bob", headers=headers).status_code == 403
