"""Every domain exception answers with its status, through the real handlers.

A bare app with one route per exception keeps this independent of any domain:
what is under test is the mapping, not who raises.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from shared.error_handlers import register_exception_handlers
from shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)


class NotYoursError(ForbiddenError):
    """Stands in for a module's own subclass, such as NotAdminError."""


class Memo(BaseModel):
    memo: str = Field(..., max_length=5)


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise/{name}")
    def raise_(name: str):
        raise RAISED[name]("사유")

    @app.post("/memo")
    def memo(body: Memo):
        return body

    return TestClient(app, raise_server_exceptions=False)


RAISED = {
    "not_found": NotFoundError,
    "unauthorized": UnauthorizedError,
    "forbidden": ForbiddenError,
    "validation": ValidationError,
    "conflict": ConflictError,
    "rate_limited": RateLimitedError,
    "unavailable": ServiceUnavailableError,
    "subclass": NotYoursError,
}


@pytest.mark.parametrize(
    "name, status",
    [
        ("not_found", 404),
        ("unauthorized", 401),
        ("forbidden", 403),
        ("validation", 400),
        ("conflict", 409),
        ("rate_limited", 429),
        ("unavailable", 502),
        ("subclass", 403),
    ],
)
def test_each_exception_answers_its_status_with_the_message_as_detail(client, name, status):
    response = client.get(f"/raise/{name}")

    assert response.status_code == status
    assert response.json() == {"detail": "사유"}


def test_only_401_says_how_to_authenticate(client):
    assert client.get("/raise/unauthorized").headers["WWW-Authenticate"] == "Bearer"
    assert "WWW-Authenticate" not in client.get("/raise/forbidden").headers


def test_a_request_schema_violation_is_one_korean_sentence(client):
    response = client.post("/memo", json={"memo": "여섯 글자 메모"})

    assert response.status_code == 422
    assert response.json() == {"detail": "메모는 5자를 넘을 수 없습니다."}
