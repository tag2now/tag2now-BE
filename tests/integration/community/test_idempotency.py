"""Idempotency-Key on the community's creating routes, against PostgreSQL."""

import asyncio

import pytest_asyncio
from sqlalchemy import text

from . import signed_in

USER = "testuser"
HEADERS = {**signed_in(USER), "Content-Type": "application/json"}


def _post(client, key, title="test", body="body"):
    return client.post(
        "/community/posts", json={"title": title, "body": body}, headers={**HEADERS, "Idempotency-Key": key}
    )


def _comment(client, post_id, key, body="hi"):
    return client.post(
        f"/community/posts/{post_id}/comments", json={"body": body}, headers={**HEADERS, "Idempotency-Key": key}
    )


def _comments_on(client, post_id):
    return client.get(f"/community/posts/{post_id}").json()["comments"]


def test_a_retried_comment_is_written_once_and_answered_alike(client):
    post_id = _post(client, "post-1").json()["id"]

    first = _comment(client, post_id, "comment-1")
    retry = _comment(client, post_id, "comment-1")

    assert (first.status_code, retry.status_code) == (201, 201)
    assert first.json() == retry.json()
    assert len(_comments_on(client, post_id)) == 1


def test_a_key_reused_for_another_comment_is_refused(client):
    post_id = _post(client, "post-1").json()["id"]
    _comment(client, post_id, "comment-1", body="hi")

    reused = _comment(client, post_id, "comment-1", body="something else")

    assert reused.status_code == 422
    assert reused.json()["detail"] == "이미 다른 요청에 쓰인 요청 키입니다. 새로고침 후 다시 시도해 주세요."
    assert len(_comments_on(client, post_id)) == 1


def test_a_failed_write_leaves_its_key_free(client):
    # The 404 rolls the claim back with the write, so the key is not spent.
    assert _comment(client, 99999, "comment-1").status_code == 404

    post_id = _post(client, "post-1").json()["id"]
    response = _comment(client, post_id, "comment-1")

    assert response.status_code == 201


def test_a_retried_post_is_written_once(client):
    first = _post(client, "post-1")
    retry = _post(client, "post-1")

    assert first.json() == retry.json()
    assert client.get("/community/posts").json()["total"] == 1


def test_one_key_spans_operations_only_once(client):
    post_id = _post(client, "shared").json()["id"]

    assert _comment(client, post_id, "shared").status_code == 422


@pytest_asyncio.fixture
async def community():
    """The real service over a real database, outside the app, so two calls can race."""
    from community.adapters.postgresql import PostgresCommunityRepository
    from community.service import CommunityService
    from idempotency.adapters.postgresql import PostgresIdempotencyStore
    from idempotency.service import IdempotencyService
    from shared.cache import cache_delete_pattern
    from shared.database import close_database, get_session_factory, init_database

    async def truncate():
        async with get_session_factory()() as session, session.begin():
            await session.execute(text("TRUNCATE posts, comments, thumbs, idempotency_keys RESTART IDENTITY CASCADE"))

    await init_database()
    await truncate()
    sessions = get_session_factory()
    yield (
        CommunityService(PostgresCommunityRepository(), sessions, IdempotencyService(PostgresIdempotencyStore())),
        sessions,
    )
    await truncate()
    await close_database()
    cache_delete_pattern("community:*")


async def test_concurrent_requests_with_one_key_write_once(community):
    from auth.models import AuthUser

    service, sessions = community
    user = AuthUser(username=USER, online_name=USER)
    post = await service.create_post(user, "t", "b", idempotency_key="post-1")

    answers = await asyncio.gather(
        *(service.create_comment(post["id"], user, "hi", idempotency_key="comment-1") for _ in range(5))
    )

    async with sessions() as session:
        written = await session.scalar(text("SELECT count(*) FROM comments"))
    assert written == 1
    assert all(answer == answers[0] for answer in answers)
