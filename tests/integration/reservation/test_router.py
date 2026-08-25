"""Reservation HTTP contract: what a client actually receives on a bad request."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture()
def client():
    from app import app

    with TestClient(app) as tc:
        yield tc


def _payload(**overrides):
    soon = (datetime.now(timezone.utc) + timedelta(hours=2)).astimezone(KST)
    body = {
        "start_time": soon.strftime("%H:%M:%S"),
        "duration_minutes": 60,
        "display_name": "Host",
        "ranks": ["Brawler"],
        "match_type": "rank_match",
        "capacity": 1,
        "memo": "",
    }
    return {**body, **overrides}


def test_a_schema_violation_names_the_field_that_failed(client):
    response = client.post("/reservations", json=_payload(duration_minutes=45))

    assert response.status_code == 422
    assert response.json() == {"detail": "예상 시간 값을 확인해 주세요."}


def test_several_bad_fields_are_all_named(client):
    response = client.post("/reservations", json=_payload(duration_minutes=45, display_name=""))

    assert response.status_code == 422
    assert response.json()["detail"] == "유저명, 예상 시간 값을 확인해 주세요."


def test_a_domain_rule_answers_400_with_its_own_message(client):
    response = client.post("/reservations", json=_payload(ranks=[]))

    assert response.status_code == 400
    assert response.json() == {"detail": "랭크매치는 보유 계급을 하나 이상 선택해야 합니다."}


def test_both_failure_kinds_share_one_response_shape(client):
    """Statuses differ by kind, but a client parses one body shape either way."""
    schema = client.post("/reservations", json=_payload(duration_minutes=45))
    domain = client.post("/reservations", json=_payload(ranks=[]))

    assert (schema.status_code, domain.status_code) == (422, 400)
    assert list(schema.json()) == list(domain.json()) == ["detail"]
    assert all(isinstance(r.json()["detail"], str) for r in (schema, domain))
