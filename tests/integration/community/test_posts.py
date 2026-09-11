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


def test_video_attachment_survives_create_detail_and_list(client):
    response = client.post('/community/posts', json={
        'title': 'video', 'body': 'combo guide', 'youtube_video_id': 'dQw4w9WgXcQ',
    }, headers=HEADERS)
    assert response.status_code == 201
    post_id = response.json()['id']
    assert client.get(f'/community/posts/{post_id}').json()['youtube_video_id'] == 'dQw4w9WgXcQ'
    posts = client.get('/community/posts').json()['posts']
    assert next(post for post in posts if post['id'] == post_id)['youtube_video_id'] == 'dQw4w9WgXcQ'
