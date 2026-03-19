"""Tests for community identity resolution."""

def test_set_identity_cookie(client):
    r = client.post("/community/identity", json={"name": "alice"})
    assert r.status_code == 200
    assert r.json()["user"] == "alice"
    assert "community_user" in r.cookies


def test_identity_from_cookie(client):
    # set cookie
    client.post("/community/identity", json={"name": "bob"})
    # use cookie (no header) to create post
    r = client.post("/community/posts", json={"body": "via cookie"})
    assert r.status_code == 201
    assert r.json()["author"] == "bob"


def test_identity_name_too_long(client):
    r = client.post("/community/identity", json={"name": "x" * 51})
    assert r.status_code == 422


def test_identity_empty_name(client):
    r = client.post("/community/identity", json={"name": ""})
    assert r.status_code == 422
