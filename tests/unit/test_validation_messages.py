"""A 422 should name the field and the rule it broke, in Korean.

These go through the HTTP layer rather than calling the handler directly: the
message a user sees is the response body, and the handler alone cannot show
that `loc` arrives as ("body", "username") — the shape that once labelled
every username error "내용".
"""

import logging

import pytest
from fastapi.testclient import TestClient

logging.disable(logging.CRITICAL)


@pytest.fixture
def client(auth_headers):
    """Signed in: the auth dependency answers 401 before the body is validated."""
    from app import app

    c = TestClient(app)
    c.headers.update(auth_headers("tester"))
    return c


@pytest.fixture
def reservation_payload():
    """A valid body, so a test's own field is the only thing that fails."""
    return {
        "start_time": "20:00",
        "match_type": "any",
        "capacity": 2,
    }


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"username": "A" * 65, "password": "pw"}, "아이디는 64자를 넘을 수 없습니다."),
        ({"username": "", "password": "pw"}, "아이디를 입력해 주세요."),
        ({"password": "pw"}, "아이디를 입력해 주세요."),
        ({"username": "alice"}, "비밀번호를 입력해 주세요."),
    ],
)
def test_login_names_the_field_that_failed(client, payload, expected):
    response = client.post("/auth/login", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == expected


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"title": "A" * 101, "body": "x"}, "제목은 100자를 넘을 수 없습니다."),
        ({"title": "", "body": "x"}, "제목을 입력해 주세요."),
        ({"title": "t", "body": "A" * 1001}, "내용은 1000자를 넘을 수 없습니다."),
        ({"title": "t", "body": "b", "post_type": "없는종류"}, "게시글 종류 값을 확인해 주세요."),
        # Characters moved to their own field; a character is no longer a post type.
        ({"title": "t", "body": "b", "post_type": "Jin"}, "게시글 종류 값을 확인해 주세요."),
        ({"title": "t", "body": "b", "characters": ["Jin", "Kazuya", "Lars"]}, "캐릭터는 2개를 넘을 수 없습니다."),
        ({"title": "t", "body": "b", "characters": ["없는캐릭터"]}, "캐릭터 값을 확인해 주세요."),
        ({"title": "t", "body": "b", "characters": ["Jin", "Jin"]}, "같은 캐릭터를 두 번 선택할 수 없습니다."),
    ],
)
def test_post_creation_names_the_field_that_failed(client, payload, expected):
    response = client.post("/community/posts", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == expected


def test_post_filter_caps_characters_at_a_team(client):
    response = client.get("/community/posts", params=[("characters", "Jin"), ("characters", "Kazuya"), ("characters", "Lars")])

    assert response.status_code == 422
    assert response.json()["detail"] == "캐릭터는 2개를 넘을 수 없습니다."


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"capacity": 0}, "모집 인원은 1 이상이어야 합니다."),
        ({"capacity": 9}, "모집 인원은 3 이하여야 합니다."),
        ({"memo": "A" * 141}, "메모는 140자를 넘을 수 없습니다."),
        ({"ranks": [f"rank{i}" for i in range(21)]}, "보유 계급은 20개를 넘을 수 없습니다."),
    ],
)
def test_reservation_names_the_bound_that_was_crossed(client, reservation_payload, override, expected):
    response = client.post("/reservations", json={**reservation_payload, **override})

    assert response.status_code == 422
    assert response.json()["detail"] == expected


def test_particle_agrees_with_the_label_it_follows(client, reservation_payload):
    """은/는 and 을/를 follow the last syllable, not a fixed "은(는)"."""
    with_final = client.post("/community/posts", json={"title": "t", "body": "A" * 1001})
    without_final = client.post("/reservations", json={**reservation_payload, "memo": "A" * 141})

    assert with_final.json()["detail"].startswith("내용은")
    assert without_final.json()["detail"].startswith("메모는")


def test_unmapped_field_still_answers_in_korean(client):
    """A field with no label must not leak pydantic's English message."""
    response = client.post("/community/posts/1/thumb", json={"direction": "sideways"})

    assert response.status_code == 422
    assert response.json()["detail"] == "추천 방향 값을 확인해 주세요."


def test_a_signed_in_route_answers_401_before_validating_the_body():
    """No token, bad body: the caller must learn to sign in, not to fix a field."""
    from app import app

    response = TestClient(app).post("/reservations", json={"memo": "A" * 141})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["detail"] == "로그인이 필요합니다."
