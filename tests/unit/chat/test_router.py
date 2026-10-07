"""The chat routes over HTTP, and the stream as the events it yields.

The stream never ends on its own, and TestClient returns a response only once
the app has finished sending it, so the stream is read by iterating the route
function itself; the POST and DELETE routes go through the HTTP layer.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from chat import router, service
from chat.adapters.memory_repository import MemoryChatRepository
from chat.adapters.memory_bus import MemoryChatEventBus
from chat.ports import ChatEventBus

logging.disable(logging.CRITICAL)


# Every read is bounded: an event that never comes would otherwise leave the
# test waiting on the queue forever instead of failing.
async def _next(events):
    return await asyncio.wait_for(anext(events), 1)


@pytest.fixture(autouse=True)
def configured():
    service.configure(MemoryChatRepository(max_kept=10), MemoryChatEventBus())


@pytest.fixture
def client():
    from app import app

    return TestClient(app)


class EndedBus(ChatEventBus):
    """A bus whose subscription ends at once, so the stream sends its snapshot
    and finishes --- which is what lets TestClient read it over HTTP."""

    async def publish(self, event):
        pass

    @asynccontextmanager
    async def subscribe(self):
        yield _no_events()


async def _no_events():
    return
    yield


def test_anyone_can_read_the_chat_without_logging_in(client, auth_headers):
    service.configure(MemoryChatRepository(max_kept=10), EndedBus())
    client.post("/chat/messages", json={"body": "hello"}, headers=auth_headers("alice"))

    response = client.get("/chat/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    event_line, data_line = response.text.strip().split("\n")
    assert event_line == "event: snapshot"
    assert [m["body"] for m in json.loads(data_line.removeprefix("data: "))] == ["hello"]


@pytest.mark.parametrize("method, path", [("POST", "/chat/messages"), ("DELETE", "/chat/messages/1")])
def test_writing_needs_a_login(client, method, path):
    response = client.request(method, path, json={"body": "hello"})

    assert response.status_code == 401


def test_a_post_answers_the_message_under_the_signed_in_name(client, auth_headers):
    response = client.post("/chat/messages", json={"body": "  한 판 하실 분  "}, headers=auth_headers("alice", "Alice"))

    assert response.status_code == 201
    body = response.json()
    assert (body["author_username"], body["author_online_name"], body["body"]) == ("alice", "Alice", "한 판 하실 분")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("   ", "내용을 입력해 주세요."),
        ("가" * 201, "내용은 200자를 넘을 수 없습니다."),
    ],
)
def test_an_empty_or_long_message_is_refused_in_korean(client, auth_headers, text, expected):
    response = client.post("/chat/messages", json={"body": text}, headers=auth_headers("alice"))

    assert response.status_code == 422
    assert response.json()["detail"] == expected


def test_flooding_answers_429(client, auth_headers):
    headers = auth_headers("alice")
    client.post("/chat/messages", json={"body": "one"}, headers=headers)

    response = client.post("/chat/messages", json={"body": "two"}, headers=headers)

    assert response.status_code == 429
    assert response.json()["detail"] == "메시지를 너무 빨리 보내고 있습니다. 잠시 후 다시 보내 주세요."


def test_delete_is_the_authors_or_an_admins(client, auth_headers):
    message_id = client.post("/chat/messages", json={"body": "mine"}, headers=auth_headers("alice")).json()["id"]

    assert client.delete(f"/chat/messages/{message_id}", headers=auth_headers("bob")).status_code == 403
    assert client.delete(f"/chat/messages/{message_id}", headers=auth_headers("mod", admin=True)).status_code == 204
    assert client.delete(f"/chat/messages/{message_id}", headers=auth_headers("alice")).status_code == 404


async def test_the_stream_opens_with_todays_messages_then_follows_changes():
    earlier = await service.post_message(subject="alice", display_name="Alice", body="earlier")
    events = router.stream()

    snapshot = await _next(events)
    assert snapshot.event == "snapshot"
    assert [m.body for m in snapshot.data] == ["earlier"]

    later = await service.post_message(subject="bob", display_name="Bob", body="later")
    posted = await _next(events)
    assert (posted.event, posted.data.id, posted.data.body) == ("message", later.id, "later")

    await service.delete_message(earlier.id, subject="alice", admin=False)
    deleted = await _next(events)
    assert (deleted.event, deleted.data.id) == ("delete", earlier.id)

    await events.aclose()


async def test_someone_who_joins_later_gets_all_of_todays_chat_then_the_same_live_events():
    first = router.stream()
    assert (await _next(first)).data == []

    lines = [await service.post_message(subject=f"user{i}", display_name=f"User{i}", body=f"line {i}") for i in range(3)]
    await service.delete_message(lines[1].id, subject="user1", admin=False)
    for _ in range(4):  # three messages and a delete, as they happened
        await _next(first)

    second = router.stream()
    snapshot = await _next(second)
    assert snapshot.event == "snapshot"
    assert [m.body for m in snapshot.data] == ["line 0", "line 2"]

    latest = await service.post_message(subject="user3", display_name="User3", body="line 3")
    for stream in (first, second):
        event = await _next(stream)
        assert (event.event, event.data.id) == ("message", latest.id)

    await first.aclose()
    await second.aclose()


class SlowReadRepository(MemoryChatRepository):
    """Reads the way a real store does: the event loop moves on mid-read.

    The in-memory store never yields while reading, so with it alone the order
    of subscribing and reading the snapshot is unobservable. This one takes its
    snapshot, then waits to be released, leaving a window another request can
    post into.
    """

    def __init__(self):
        super().__init__(max_kept=10)
        self.reading = asyncio.Event()
        self.release = asyncio.Event()

    async def list_since(self, boundary):
        snapshot = await super().list_since(boundary)
        self.reading.set()
        await self.release.wait()
        return snapshot


async def test_a_message_posted_while_the_snapshot_is_read_still_reaches_the_new_reader():
    repository = SlowReadRepository()
    service.configure(repository, MemoryChatEventBus())
    events = router.stream()

    opening = asyncio.ensure_future(_next(events))
    await asyncio.wait_for(repository.reading.wait(), 1)
    posted = await service.post_message(subject="alice", display_name="Alice", body="in the gap")
    repository.release.set()

    snapshot = await opening
    assert snapshot.data == []  # read before the post landed
    live = await _next(events)
    assert (live.event, live.data.id) == ("message", posted.id)

    await events.aclose()
