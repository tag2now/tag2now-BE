"""Notices are pinned above the board and managed by every admin together."""

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


SECOND_ADMIN = {**signed_in("second", admin=True), "Content-Type": "application/json"}
EDIT = {"title": "edited", "body": "b", "post_type": "공지", "characters": [], "youtube_video_id": None}


def test_another_admin_edits_and_deletes_a_notice(client):
    notice = _post(client, ADMIN, "notice", "공지")

    assert client.patch(f"/community/posts/{notice}", json=EDIT, headers=SECOND_ADMIN).status_code == 200
    assert client.get(f"/community/posts/{notice}").json()["title"] == "edited"

    assert client.delete(f"/community/posts/{notice}", headers=SECOND_ADMIN).status_code == 204
    assert client.get(f"/community/posts/{notice}").status_code == 404


def test_an_admin_cannot_manage_a_players_post(client):
    post_id = _post(client, USER, "post", "자유")

    assert client.patch(f"/community/posts/{post_id}", json=EDIT, headers=SECOND_ADMIN).status_code == 403
    assert client.delete(f"/community/posts/{post_id}", headers=SECOND_ADMIN).status_code == 403
    assert client.get(f"/community/posts/{post_id}").json()["post_type"] == "자유"
