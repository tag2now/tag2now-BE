"""Character tags through the public request models and the list route."""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from community.models import CreatePostRequest, UpdatePostRequest
from community.router import router


def test_create_defaults_to_no_characters():
    assert CreatePostRequest(title='t', body='b').characters == []


def test_create_keeps_the_team_in_submitted_order():
    assert CreatePostRequest(title='t', body='b', characters=['Kazuya', 'Jin']).characters == ['Kazuya', 'Jin']


def test_edit_requires_an_explicit_character_list():
    with pytest.raises(ValidationError):
        UpdatePostRequest(title='t', body='b', post_type='공략', youtube_video_id=None)


@pytest.fixture
def listing(monkeypatch):
    from community import service
    from shared.cache import cache_delete_pattern

    repo = AsyncMock()
    repo.list_posts.return_value = ([], 0)
    monkeypatch.setattr(service, 'get_repo', lambda: repo)
    app = FastAPI()
    app.include_router(router, prefix='/community')
    cache_delete_pattern('community:*')
    with TestClient(app) as client:
        yield client, repo
    cache_delete_pattern('community:*')


def test_list_passes_the_team_regardless_of_order(listing):
    client, repo = listing

    client.get('/community/posts', params=[('characters', 'Kazuya'), ('characters', 'Jin')])
    client.get('/community/posts', params=[('characters', 'Jin'), ('characters', 'Kazuya')])

    # Both orders name the same team, so the second read is served from cache.
    repo.list_posts.assert_awaited_once_with(1, 20, None, ['Jin', 'Kazuya'])


def test_list_without_characters_filters_nothing(listing):
    client, repo = listing

    client.get('/community/posts', params={'post_type': '공략'})

    repo.list_posts.assert_awaited_once_with(1, 20, '공략', [])
