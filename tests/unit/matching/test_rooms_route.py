"""GET /rooms/all joins the room list with who is live, as the router composes them."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from matching.dependencies import matching_service
from streaming.dependencies import streaming_service

LIVE = {"platform": "chzzk", "channel_name": "앨리스", "url": "https://chzzk.naver.com/live/" + "a" * 32,
        "title": "TTT2 랭크전", "viewer_count": 42}


def _room(*npids):
    return {"room_id": 1, "owner_npid": npids[0], "users": [{"npid": npid, "online_name": npid} for npid in npids]}


ROOMS = {"rank_match": [_room("Alice", "bob")], "player_match": [_room("carol")]}


@pytest.fixture
def services():
    from app import app

    matching = AsyncMock()
    matching.get_rooms_all.return_value = ROOMS
    streaming = AsyncMock()
    app.dependency_overrides[matching_service] = lambda: matching
    app.dependency_overrides[streaming_service] = lambda: streaming
    yield TestClient(app), streaming  # no `with`: lifespan stays off, the services are ours
    app.dependency_overrides.pop(matching_service)
    app.dependency_overrides.pop(streaming_service)


def _streams(body):
    return {u["npid"]: u["stream"] for rooms in body.values() for room in rooms for u in room["users"]}


def test_each_user_is_marked_with_their_broadcast(services):
    client, streaming = services
    streaming.live_or_empty.return_value = {"alice": LIVE}

    body = client.get("/rooms/all").json()

    assert _streams(body) == {"Alice": LIVE, "bob": None, "carol": None}
    streaming.live_or_empty.assert_awaited_once_with({"Alice", "bob", "carol"})


def test_nobody_live_still_answers_every_room(services):
    client, streaming = services
    streaming.live_or_empty.return_value = {}

    assert _streams(client.get("/rooms/all").json()) == {"Alice": None, "bob": None, "carol": None}
