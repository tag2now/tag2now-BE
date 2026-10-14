"""GET /game-data: the character and rank tables tag2now-save-admin reads."""

import pytest

from matching.constants import TEKKEN_RANKS, TTT2_CHARACTERS


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)  # no `with`: lifespan stays off, nothing here needs it


def test_lists_every_character_slot_in_id_order(client):
    characters = client.get("/game-data").json()["characters"]

    assert [c["id"] for c in characters] == list(range(59))
    assert characters[0] == {"id": 0, "name": "Paul"}
    assert {c["id"]: c["name"] for c in characters} == TTT2_CHARACTERS


def test_lists_every_rank_code_with_its_tier(client):
    ranks = client.get("/game-data").json()["ranks"]

    assert [r["id"] for r in ranks] == list(range(43))
    assert ranks[-1] == {"id": 42, "name": "True Tekken God", "tier": "God"}
    assert {r["id"]: {"name": r["name"], "tier": r["tier"]} for r in ranks} == TEKKEN_RANKS


def test_lets_clients_keep_it_for_five_minutes(client):
    response = client.get("/game-data")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
