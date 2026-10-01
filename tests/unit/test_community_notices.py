"""Notices: only an admin may write one, through the public routes."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

NOTICE = {"title": "점검 안내", "body": "내일 점검합니다", "post_type": "공지"}
EDIT = {**NOTICE, "characters": [], "youtube_video_id": None}


@pytest.fixture
def board(monkeypatch):
    from app import app
    from community import service
    from shared.cache import cache_delete_pattern

    repo = AsyncMock()
    repo.create_post.return_value = {}
    repo.update_post.return_value = {
        "id": 1, "author": "root", "title": "t", "body": "b", "post_type": "공지",
        "characters": [], "youtube_video_id": None, "thumbs_up": 0, "thumbs_down": 0,
        "created_at": "2026-10-01T00:00:00Z", "comment_count": 0,
    }
    monkeypatch.setattr(service, "get_repo", lambda: repo)
    cache_delete_pattern("community:*")
    # No `with`: lifespan stays off, the repository is ours.
    yield TestClient(app), repo
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


def test_non_admin_cannot_turn_a_post_into_a_notice(board, auth_headers):
    client, repo = board

    response = client.patch("/community/posts/1", json=EDIT, headers=auth_headers("alice"))

    assert response.status_code == 403
    repo.update_post.assert_not_awaited()


def test_admin_edits_a_notice(board, auth_headers):
    client, repo = board

    response = client.patch("/community/posts/1", json=EDIT, headers=auth_headers("root", admin=True))

    assert response.status_code == 200
    repo.update_post.assert_awaited_once()


def test_non_admin_still_posts_other_types(board, auth_headers):
    client, repo = board

    response = client.post("/community/posts", json={**NOTICE, "post_type": "자유"}, headers=auth_headers("alice"))

    assert response.status_code == 201
