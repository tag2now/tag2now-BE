"""Idempotency: what counts as the same request, and replaying its answer."""

from datetime import datetime, time, timezone

import pytest
from fastapi.testclient import TestClient

from idempotency.domain import fingerprint
from idempotency.exceptions import IdempotencyKeyReusedError


def test_the_same_request_has_the_same_fingerprint_whatever_its_key_order():
    assert fingerprint("community.comment", {"body": "hi", "post_id": 1}) == fingerprint(
        "community.comment", {"post_id": 1, "body": "hi"}
    )


def test_a_different_input_or_operation_has_a_different_fingerprint():
    request = {"post_id": 1, "body": "hi"}

    assert fingerprint("community.comment", request) != fingerprint("community.comment", {**request, "body": "hi!"})
    assert fingerprint("community.comment", request) != fingerprint("community.post", request)


def test_a_fingerprint_takes_times_and_enums():
    from reservation.domain import MatchType

    request = {"start_time": time(20, 30), "match_type": MatchType.RANK}

    assert fingerprint("reservation.create", request) == fingerprint("reservation.create", dict(request))


async def test_a_retry_replays_the_first_answer_without_writing_again(idempotency, sessions):
    writes = []

    async def write():
        writes.append(1)
        return {"id": len(writes), "created_at": datetime(2026, 11, 6, tzinfo=timezone.utc)}

    async with sessions() as session:
        first = await idempotency.run_once(session, "alice", "k1", "community.comment", {"body": "hi"}, write)
        second = await idempotency.run_once(session, "alice", "k1", "community.comment", {"body": "hi"}, write)

    assert writes == [1]
    assert first == second == {"id": 1, "created_at": "2026-11-06T00:00:00Z"}


async def test_a_key_is_each_users_own(idempotency, sessions):
    async def write():
        return {"ok": True}

    async with sessions() as session:
        await idempotency.run_once(session, "alice", "k1", "community.comment", {"body": "hi"}, write)
        # Same key, other user, other request: no clash.
        assert await idempotency.run_once(session, "bob", "k1", "community.comment", {"body": "yo"}, write) == {
            "ok": True
        }


async def test_a_key_spent_on_another_request_is_refused(idempotency, sessions):
    async def write():
        return {"ok": True}

    async with sessions() as session:
        await idempotency.run_once(session, "alice", "k1", "community.comment", {"body": "hi"}, write)
        with pytest.raises(IdempotencyKeyReusedError):
            await idempotency.run_once(session, "alice", "k1", "community.comment", {"body": "bye"}, write)


@pytest.fixture
def board(sessions, idempotency):
    from unittest.mock import AsyncMock

    from app import app
    from community.dependencies import community_service
    from community.service import CommunityService

    app.dependency_overrides[community_service] = lambda: CommunityService(AsyncMock(), sessions, idempotency)
    yield TestClient(app)
    app.dependency_overrides.pop(community_service)


def test_a_creating_route_without_a_key_names_it(board, auth_headers):
    response = board.post("/community/posts/1/comments", json={"body": "hi"}, headers=auth_headers("alice"))

    assert (response.status_code, response.json()["detail"]) == (422, "요청 키를 입력해 주세요.")


def test_an_anonymous_caller_is_told_to_sign_in_before_the_key_is_checked(board):
    response = board.post("/community/posts/1/comments", json={"body": "hi"})

    assert response.status_code == 401
