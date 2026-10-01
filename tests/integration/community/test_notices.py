"""Notices are pinned above the board, so the board's own list leaves them out."""

from . import signed_in

ADMIN = {**signed_in("root", admin=True), "Content-Type": "application/json"}
USER = {**signed_in("testuser"), "Content-Type": "application/json"}


def _post(client, headers, title, post_type):
    response = client.post("/community/posts", json={"title": title, "body": "b", "post_type": post_type}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_the_list_leaves_notices_out(client):
    _post(client, ADMIN, "notice", "공지")
    post_id = _post(client, USER, "post", "자유")

    data = client.get("/community/posts").json()

    assert [p["id"] for p in data["posts"]] == [post_id]
    assert data["total"] == 1


def test_notices_are_listed_on_their_own_newest_first(client):
    older = _post(client, ADMIN, "older", "공지")
    newer = _post(client, ADMIN, "newer", "공지")
    _post(client, USER, "post", "자유")

    data = client.get("/community/posts", params={"post_type": "공지"}).json()

    assert [p["id"] for p in data["posts"]] == [newer, older]
    assert data["total"] == 2


def test_a_new_notice_shows_up_past_a_cached_list(client):
    client.get("/community/posts", params={"post_type": "공지"})
    notice = _post(client, ADMIN, "notice", "공지")

    posts = client.get("/community/posts", params={"post_type": "공지"}).json()["posts"]

    assert [p["id"] for p in posts] == [notice]
