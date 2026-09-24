from datetime import datetime

import pytest

from . import signed_in

HEADERS = signed_in('edit-owner')
EDIT = {'title': '수정 제목', 'body': '수정 본문', 'post_type': '공략', 'characters': ['Jin', 'Devil Jin'], 'youtube_video_id': 'aqz-KE-bpKQ'}


def create(client):
    response = client.post('/community/posts', headers=HEADERS, json={
        'title': 'original', 'body': 'original body', 'youtube_video_id': 'M7lc1UVf-VE',
    })
    assert response.status_code == 201
    return response.json()


def test_edit_refreshes_cached_detail_and_filtered_lists_and_preserves_reactions(client):
    original = create(client)
    url = f"/community/posts/{original['id']}"
    client.post(f'{url}/comments', headers=HEADERS, json={'body': 'keep comment'})
    client.post(f'{url}/thumb', headers=HEADERS, json={'direction': 'up'})
    client.get(url)
    client.get('/community/posts?post_type=자유')
    client.get('/community/posts?post_type=공략')
    response = client.patch(url, headers=HEADERS, json=EDIT)
    assert response.status_code == 200
    assert response.json()['comment_count'] == 1
    detail = client.get(url).json()
    for key, value in EDIT.items():
        assert detail[key] == value
    assert detail['author'] == original['author']
    assert datetime.fromisoformat(detail['created_at']) == datetime.fromisoformat(original['created_at'])
    assert detail['thumbs_up'] == 1
    assert detail['comments'][0]['body'] == 'keep comment'
    assert not client.get('/community/posts?post_type=자유').json()['posts']
    assert client.get('/community/posts?post_type=공략').json()['posts'][0]['title'] == EDIT['title']
    response = client.patch(url, headers=HEADERS, json={**EDIT, 'youtube_video_id': None})
    assert response.status_code == 200
    assert client.get(url).json()['youtube_video_id'] is None


def test_edit_requires_owner_and_existing_post(client):
    original = create(client)
    url = f"/community/posts/{original['id']}"
    assert client.patch(url, headers=signed_in('other'), json=EDIT).status_code == 403
    assert client.patch(url, json=EDIT).status_code == 401
    assert client.get(url).json()['title'] == 'original'
    assert client.patch('/community/posts/9999999', headers=HEADERS, json=EDIT).status_code == 404


@pytest.mark.parametrize('change', [
    {'title': ''}, {'title': '   '}, {'title': 'x' * 101},
    {'body': '\n  '}, {'body': 'x' * 1001}, {'post_type': 'invalid'}, {'post_type': 'Jin'},
    {'characters': ['Jin', 'Kazuya', 'Lars']}, {'characters': ['Jin', 'Jin']}, {'characters': ['invalid']},
    {'youtube_video_id': 'https://youtu.be/M7lc1UVf-VE'},
])
def test_edit_rejects_invalid_fields_without_changing_post(client, change):
    original = create(client)
    url = f"/community/posts/{original['id']}"
    assert client.patch(url, headers=HEADERS, json={**EDIT, **change}).status_code == 422
    assert client.get(url).json()['title'] == 'original'


@pytest.mark.parametrize('field', ['youtube_video_id', 'characters'])
def test_edit_requires_explicit_removable_fields(client, field):
    original = create(client)
    payload = {key: value for key, value in EDIT.items() if key != field}
    assert client.patch(f"/community/posts/{original['id']}", headers=HEADERS, json=payload).status_code == 422
