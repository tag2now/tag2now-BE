"""Comment deletion: the author's or any admin's, and a deleted comment stays only above live replies."""

from unittest.mock import ANY, AsyncMock

import pytest
from fastapi.testclient import TestClient

from auth.models import AuthUser
from community.exceptions import OwnershipError
from community.service import ensure_can_delete_comment

POST = {
    "id": 1,
    "author": "alice",
    "title": "t",
    "body": "b",
    "post_type": "자유",
    "characters": [],
    "youtube_video_id": None,
    "thumbs_up": 0,
    "thumbs_down": 0,
    "created_at": "2026-10-01T00:00:00Z",
}


def comment(id: int, parent_id: int | None = None, deleted: bool = False, author: str = "bob") -> dict:
    return {
        "id": id,
        "post_id": 1,
        "parent_id": parent_id,
        "author": author,
        "body": f"comment {id}",
        "created_at": "2026-10-01T00:00:00Z",
        "deleted_at": "2026-10-02T00:00:00Z" if deleted else None,
    }


def user(username: str, admin: bool = False) -> AuthUser:
    return AuthUser(username=username, online_name=username, admin=admin)


@pytest.fixture
def board(sessions):
    from app import app
    from community.dependencies import community_service
    from community.service import CommunityService
    from shared.cache import cache_delete_pattern

    repo = AsyncMock()
    repo.get_post.return_value = dict(POST)
    repo.get_comment.return_value = comment(7, author="bob")
    app.dependency_overrides[community_service] = lambda: CommunityService(repo, sessions)
    cache_delete_pattern("community:*")
    # No `with`: lifespan stays off, the service is ours.
    yield TestClient(app), repo
    app.dependency_overrides.pop(community_service)
    cache_delete_pattern("community:*")


def test_the_author_may_delete_their_comment():
    ensure_can_delete_comment(comment(7, author="bob"), user("bob"))


def test_an_admin_may_delete_anyones_comment():
    ensure_can_delete_comment(comment(7, author="bob"), user("root", admin=True))


def test_nobody_else_may_delete_a_comment():
    with pytest.raises(OwnershipError):
        ensure_can_delete_comment(comment(7, author="bob"), user("mallory"))


def test_delete_route_soft_deletes_after_the_rule(board, auth_headers):
    client, repo = board

    response = client.delete("/community/posts/1/comments/7", headers=auth_headers("root", admin=True))

    assert response.status_code == 204
    repo.get_comment.assert_awaited_once_with(ANY, 1, 7)
    repo.delete_comment.assert_awaited_once_with(ANY, 7)


def test_delete_route_refuses_a_stranger(board, auth_headers):
    client, repo = board

    response = client.delete("/community/posts/1/comments/7", headers=auth_headers("mallory"))

    assert response.status_code == 403
    repo.delete_comment.assert_not_awaited()


def test_deleted_comment_with_a_live_reply_stays_without_its_words(board):
    client, repo = board
    repo.get_post_comments.return_value = [comment(1, deleted=True), comment(2, parent_id=1)]

    [head] = client.get("/community/posts/1").json()["comments"]

    assert (head["id"], head["deleted"], head["body"]) == (1, True, "")
    assert [(r["id"], r["deleted"]) for r in head["replies"]] == [(2, False)]


def test_deleted_comments_with_nothing_live_under_them_are_gone(board):
    client, repo = board
    repo.get_post_comments.return_value = [
        comment(1, deleted=True),
        comment(2),
        comment(3, parent_id=2, deleted=True),
        comment(4, deleted=True),
        comment(5, parent_id=4, deleted=True),
    ]

    comments = client.get("/community/posts/1").json()["comments"]

    assert [(c["id"], c["replies"]) for c in comments] == [(2, [])]
