"""Tests for community thumbs: one final vote per user and post."""

from . import signed_in

USER = "testuser"
HEADERS = {**signed_in(USER), "Content-Type": "application/json"}


def _create_post(client, body="test post"):
    r = client.post("/community/posts", json={"title": "test", "body": body}, headers=HEADERS)
    return r.json()["id"]


def test_thumb_up_post(client):
    post_id = _create_post(client)
    r = client.post(f"/community/posts/{post_id}/thumb", json={"direction": "up"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["thumbs_up"] == 1
    assert r.json()["thumbs_down"] == 0


def _thumb(client, post_id, direction):
    return client.post(f"/community/posts/{post_id}/thumb", json={"direction": direction}, headers=HEADERS)


def test_second_vote_same_direction_is_refused(client):
    post_id = _create_post(client)
    _thumb(client, post_id, "up")
    r = _thumb(client, post_id, "up")
    assert r.status_code == 409
    assert r.json()["detail"] == "이미 추천·비추천한 글입니다."
    assert client.get(f"/community/posts/{post_id}").json()["thumbs_up"] == 1


def test_second_vote_other_direction_is_refused(client):
    post_id = _create_post(client)
    _thumb(client, post_id, "up")
    r = _thumb(client, post_id, "down")
    assert r.status_code == 409
    post = client.get(f"/community/posts/{post_id}").json()
    assert (post["thumbs_up"], post["thumbs_down"]) == (1, 0)


def test_thumb_invalid_direction(client):
    post_id = _create_post(client)
    r = client.post(f"/community/posts/{post_id}/thumb", json={"direction": "sideways"}, headers=HEADERS)
    assert r.status_code == 422


def test_thumb_nonexistent_post(client):
    r = client.post("/community/posts/99999/thumb", json={"direction": "up"}, headers=HEADERS)
    assert r.status_code == 404
