"""A 422 should name the field and the rule it broke, in Korean.

These go through the HTTP layer rather than calling the handler directly: the
message a user sees is the response body, and the handler alone cannot show
that `loc` arrives as ("body", "name") — the shape that once labelled every
username error "내용".
"""

import logging

import pytest
from fastapi.testclient import TestClient

logging.disable(logging.CRITICAL)


@pytest.fixture
def client():
    from app import app

    c = TestClient(app)
    c.cookies.set("community_user", "tester")
    return c


@pytest.fixture
def reservation_payload():
    """A valid body, so a test's own field is the only thing that fails."""
    return {
        "start_time": "20:00",
        "duration_minutes": 60,
        "display_name": "tester",
        "match_type": "any",
        "capacity": 2,
    }


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"name": "A" * 51}, "유저명은 50자를 넘을 수 없습니다."),
        ({"name": ""}, "유저명을 입력해 주세요."),
        ({}, "유저명을 입력해 주세요."),
    ],
)
def test_identity_names_the_username_rule(client, payload, expected):
    response = client.post("/community/identity", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == expected


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"title": "A" * 101, "body": "x"}, "제목은 100자를 넘을 수 없습니다."),
        ({"title": "", "body": "x"}, "제목을 입력해 주세요."),
        ({"title": "t", "body": "A" * 1001}, "내용은 1000자를 넘을 수 없습니다."),
        ({"title": "t", "body": "b", "post_type": "없는종류"}, "게시글 종류 값을 확인해 주세요."),
    ],
)
def test_post_creation_names_the_field_that_failed(client, payload, expected):
    response = client.post("/community/posts", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == expected


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"duration_minutes": 15}, "예상 시간은 30 이상이어야 합니다."),
        ({"duration_minutes": 300}, "예상 시간은 240 이하여야 합니다."),
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
    with_final = client.post("/community/identity", json={"name": "A" * 51})
    without_final = client.post("/reservations", json={**reservation_payload, "memo": "A" * 141})

    assert with_final.json()["detail"].startswith("유저명은")
    assert without_final.json()["detail"].startswith("메모는")


def test_unmapped_field_still_answers_in_korean(client):
    """A field with no label must not leak pydantic's English message."""
    response = client.post("/community/posts/1/thumb", json={"direction": "sideways"})

    assert response.status_code == 422
    assert response.json()["detail"] == "추천 방향 값을 확인해 주세요."
