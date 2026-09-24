"""YouTube attachments through public request models and HTTP endpoints."""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from community.models import CreatePostRequest
from community.router import router


@pytest.mark.parametrize('value', ['', 'short', 'x' * 12, 'https://youtu.be/dQw4w9WgXcQ', 'dQw4w9WgXc!', 'dQw4w9WgXcQ\n'])
def test_reject_invalid_video_id(value):
    with pytest.raises(ValidationError):
        CreatePostRequest(title='test', body='body', youtube_video_id=value)


def test_existing_request_has_no_video():
    assert CreatePostRequest(title='test', body='body').youtube_video_id is None


@pytest.mark.parametrize('video_id', [None, 'dQw4w9WgXcQ'])
def test_create_and_read_video_through_api(monkeypatch, video_id, auth_headers):
    from community import service
    from shared.cache import cache_delete_pattern

    post = dict(id=987654, author='testuser', title='test', body='body', post_type='자유',
                thumbs_up=0, thumbs_down=0, created_at='2026-09-11T00:00:00Z',
                youtube_video_id=video_id)
    repo = AsyncMock()
    repo.create_post.return_value = post.copy()
    repo.get_post.return_value = post.copy()
    repo.get_post_comments.return_value = []
    repo.list_posts.return_value = ([post.copy()], 1)
    monkeypatch.setattr(service, 'get_repo', lambda: repo)
    app = FastAPI()
    app.include_router(router, prefix='/community')
    cache_delete_pattern('community:*')
    try:
        with TestClient(app) as client:
            response = client.post('/community/posts', json={
                'title': 'test', 'body': 'body', 'youtube_video_id': video_id,
            }, headers=auth_headers('testuser'))
            assert response.status_code == 201
            repo.create_post.assert_awaited_once_with('testuser', 'test', 'body', '자유', [], video_id)
            assert response.json()['youtube_video_id'] == video_id
            assert client.get('/community/posts/987654').json()['youtube_video_id'] == video_id
            assert client.get('/community/posts').json()['posts'][0]['youtube_video_id'] == video_id
            invalid = client.post('/community/posts', json={
                'title': 'test', 'body': 'body', 'youtube_video_id': '<iframe>',
            }, headers=auth_headers('testuser'))
            assert invalid.status_code == 422
            assert repo.create_post.await_count == 1
    finally:
        cache_delete_pattern('community:*')
