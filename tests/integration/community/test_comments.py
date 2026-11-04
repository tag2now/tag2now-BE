"""Tests for community comments."""

from . import signed_in

USER = "testuser"
HEADERS = {**signed_in(USER), "Content-Type": "application/json"}


def _create_post(client, body="test post"):
    r = client.post("/community/posts", json={"title": "test", "body": body}, headers=HEADERS)
    return r.json()["id"]


def test_create_comment(client):
    post_id = _create_post(client)
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "nice post"},
        headers=HEADERS,
    )
    assert r.status_code == 201
    assert r.json()["body"] == "nice post"
    assert r.json()["post_id"] == post_id
    assert r.json()["parent_id"] is None


def test_create_reply(client):
    post_id = _create_post(client)
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "parent"},
        headers=HEADERS,
    )
    parent_id = r.json()["id"]

    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "reply", "parent_id": parent_id},
        headers=HEADERS,
    )
    assert r.status_code == 201
    assert r.json()["parent_id"] == parent_id


def test_reject_nested_reply(client):
    post_id = _create_post(client)
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "parent"},
        headers=HEADERS,
    )
    parent_id = r.json()["id"]

    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "reply", "parent_id": parent_id},
        headers=HEADERS,
    )
    reply_id = r.json()["id"]

    # try replying to the reply — should fail
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "nested", "parent_id": reply_id},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_comments_appear_in_post_detail(client):
    post_id = _create_post(client)
    client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "c1"},
        headers=HEADERS,
    )

    r = client.get(f"/community/posts/{post_id}")
    assert len(r.json()["comments"]) == 1
    assert r.json()["comments"][0]["body"] == "c1"


# -- Deletion ----------------------------------------------------------------

OTHER = signed_in("other")
ADMIN = signed_in("root", admin=True)


def _comment(client, post_id, body="c", parent_id=None, headers=HEADERS):
    payload = {"body": body, **({"parent_id": parent_id} if parent_id else {})}
    r = client.post(f"/community/posts/{post_id}/comments", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _delete(client, post_id, comment_id, headers=HEADERS):
    return client.delete(f"/community/posts/{post_id}/comments/{comment_id}", headers=headers)


def test_author_deletes_their_comment(client):
    post_id = _create_post(client)
    comment_id = _comment(client, post_id)

    assert _delete(client, post_id, comment_id).status_code == 204
    assert client.get(f"/community/posts/{post_id}").json()["comments"] == []


def test_admin_deletes_anyones_comment(client):
    post_id = _create_post(client)
    comment_id = _comment(client, post_id)

    assert _delete(client, post_id, comment_id, headers=ADMIN).status_code == 204
    assert client.get(f"/community/posts/{post_id}").json()["comments"] == []


def test_someone_else_cannot_delete_a_comment(client):
    post_id = _create_post(client)
    comment_id = _comment(client, post_id)

    assert _delete(client, post_id, comment_id, headers=OTHER).status_code == 403
    assert len(client.get(f"/community/posts/{post_id}").json()["comments"]) == 1


def test_anonymous_delete_is_401(client):
    post_id = _create_post(client)
    comment_id = _comment(client, post_id)

    assert _delete(client, post_id, comment_id, headers={}).status_code == 401


def test_missing_deleted_or_mismatched_comment_is_404(client):
    post_id = _create_post(client)
    other_post_id = _create_post(client)
    comment_id = _comment(client, post_id)

    assert _delete(client, post_id, 9999).status_code == 404
    assert _delete(client, other_post_id, comment_id).status_code == 404
    _delete(client, post_id, comment_id)
    assert _delete(client, post_id, comment_id).status_code == 404


def test_deleted_parent_stays_as_a_placeholder_above_its_replies(client):
    post_id = _create_post(client)
    parent_id = _comment(client, post_id, body="parent")
    _comment(client, post_id, body="reply", parent_id=parent_id, headers=OTHER)

    _delete(client, post_id, parent_id)

    [head] = client.get(f"/community/posts/{post_id}").json()["comments"]
    assert (head["id"], head["deleted"], head["body"]) == (parent_id, True, "")
    assert [r["body"] for r in head["replies"]] == ["reply"]


def test_a_deleted_comment_takes_no_replies(client):
    post_id = _create_post(client)
    parent_id = _comment(client, post_id)
    _delete(client, post_id, parent_id)

    r = client.post(
        f"/community/posts/{post_id}/comments", json={"body": "late", "parent_id": parent_id}, headers=HEADERS
    )

    assert r.status_code == 404


def test_deleted_comments_leave_the_list_count(client):
    post_id = _create_post(client)
    _comment(client, post_id)
    _delete(client, post_id, _comment(client, post_id))

    [post] = client.get("/community/posts").json()["posts"]

    assert post["comment_count"] == 1
