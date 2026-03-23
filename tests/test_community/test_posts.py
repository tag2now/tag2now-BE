"""Tests for community post CRUD."""

USER = "testuser"
HEADERS = {"X-Community-User": USER, "Content-Type": "application/json"}


def test_create_and_list_posts(client):
    # Create a post
    r = client.post("/community/posts", json={"title": "test", "body": "hello world"}, headers=HEADERS)
    assert r.status_code == 201
    post = r.json()
    assert post["author"] == USER
    assert post["body"] == "hello world"
    post_id = post["id"]

    # List posts
    r = client.get("/community/posts")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(p["id"] == post_id for p in data["posts"])


def test_get_post_detail(client):
    r = client.post("/community/posts", json={"title": "test", "body": "detail test"}, headers=HEADERS)
    post_id = r.json()["id"]

    r = client.get(f"/community/posts/{post_id}")
    assert r.status_code == 200
    assert r.json()["body"] == "detail test"
    assert r.json()["comments"] == []


def test_delete_post(client):
    r = client.post("/community/posts", json={"title": "test", "body": "to delete"}, headers=HEADERS)
    post_id = r.json()["id"]

    r = client.delete(f"/community/posts/{post_id}", headers=HEADERS)
    assert r.status_code == 204

    r = client.get(f"/community/posts/{post_id}")
    assert r.status_code == 404


def test_delete_post_forbidden(client):
    r = client.post("/community/posts", json={"title": "test", "body": "not yours"}, headers=HEADERS)
    post_id = r.json()["id"]

    other = {"X-Community-User": "other", "Content-Type": "application/json"}
    r = client.delete(f"/community/posts/{post_id}", headers=other)
    assert r.status_code == 403


def test_create_post_no_identity(client):
    r = client.post("/community/posts", json={"title": "test", "body": "anon"})
    assert r.status_code == 400


def test_post_body_too_long(client):
    r = client.post("/community/posts", json={"title": "test", "body": "x" * 1001}, headers=HEADERS)
    assert r.status_code == 422
