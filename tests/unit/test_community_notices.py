"""Notices: only an admin may write one, and every admin may manage one."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

NOTICE = {"title": "점검 안내", "body": "내일 점검합니다", "post_type": "공지"}
EDIT = {**NOTICE, "characters": [], "youtube_video_id": None}


def stored(author: str, post_type: str) -> dict:
    return {
        "id": 1, "author": author, "title": "t", "body": "b", "post_type": post_type,
        "characters": [], "youtube_video_id": None, "thumbs_up": 0, "thumbs_down": 0,
        "created_at": "2026-10-01T00:00:00Z", "comment_count": 0,
    }


@pytest.fixture
def board():
    from app import app
    from community.dependencies import community_service
    from community.service import CommunityService
    from shared.cache import cache_delete_pattern

    repo = AsyncMock()
    repo.create_post.return_value = {}
    # A notice written by `root`; a test about another post says so.
    repo.get_post.return_value = stored("root", "공지")
    repo.update_post.return_value = stored("root", "공지")
    app.dependency_overrides[community_service] = lambda: CommunityService(repo)
    cache_delete_pattern("community:*")
    # No `with`: lifespan stays off, the service is ours.
    yield TestClient(app), repo
    app.dependency_overrides.pop(community_service)
    cache_delete_pattern("community:*")


def test_admin_posts_a_notice_as_themselves(board, auth_headers):
    client, repo = board

    response = client.post("/community/posts", json=NOTICE, headers=auth_headers("root", admin=True))

    assert response.status_code == 201
    repo.create_post.assert_awaited_once_with("root", "점검 안내", "내일 점검합니다", "공지", [], None)


def test_non_admin_cannot_post_a_notice(board, auth_headers):
    client, repo = board

    response = client.post("/community/posts", json=NOTICE, headers=auth_headers("alice"))

    assert response.status_code == 403
    assert response.json()["detail"] == "공지는 관리자만 작성할 수 있습니다."
    repo.create_post.assert_not_awaited()


def test_non_admin_cannot_turn_their_own_post_into_a_notice(board, auth_headers):
    client, repo = board
    repo.get_post.return_value = stored("alice", "자유")

    response = client.patch("/community/posts/1", json=EDIT, headers=auth_headers("alice"))

    assert response.status_code == 403
    repo.update_post.assert_not_awaited()


def test_non_admin_still_posts_other_types(board, auth_headers):
    client, repo = board

    response = client.post("/community/posts", json={**NOTICE, "post_type": "자유"}, headers=auth_headers("alice"))

    assert response.status_code == 201


# -- Managing a notice: every admin's, not only its author's ------------------

def test_admin_edits_another_admins_notice(board, auth_headers):
    client, repo = board

    response = client.patch("/community/posts/1", json=EDIT, headers=auth_headers("second", admin=True))

    assert response.status_code == 200
    repo.update_post.assert_awaited_once_with(1, "점검 안내", "내일 점검합니다", "공지", [], None)


def test_admin_deletes_another_admins_notice(board, auth_headers):
    client, repo = board

    response = client.delete("/community/posts/1", headers=auth_headers("second", admin=True))

    assert response.status_code == 204
    repo.delete_post.assert_awaited_once_with(1)


def test_non_admin_cannot_edit_a_notice(board, auth_headers):
    client, repo = board

    # 자유, so the post-type rule passes and only ownership is left to refuse it.
    response = client.patch("/community/posts/1", json={**EDIT, "post_type": "자유"}, headers=auth_headers("alice"))

    assert response.status_code == 403
    repo.update_post.assert_not_awaited()


def test_non_admin_cannot_delete_a_notice(board, auth_headers):
    client, repo = board

    response = client.delete("/community/posts/1", headers=auth_headers("alice"))

    assert response.status_code == 403
    repo.delete_post.assert_not_awaited()


def test_admin_cannot_take_over_a_players_post_by_making_it_a_notice(board, auth_headers):
    client, repo = board
    repo.get_post.return_value = stored("alice", "자유")

    response = client.patch("/community/posts/1", json=EDIT, headers=auth_headers("root", admin=True))

    assert response.status_code == 403
    repo.update_post.assert_not_awaited()


def test_admin_cannot_delete_a_players_post(board, auth_headers):
    client, repo = board
    repo.get_post.return_value = stored("alice", "자유")

    response = client.delete("/community/posts/1", headers=auth_headers("root", admin=True))

    assert response.status_code == 403
    repo.delete_post.assert_not_awaited()
