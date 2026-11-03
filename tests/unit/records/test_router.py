"""GET /records/matches: its query, and the shape a recorded match answers in."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from records.dependencies import records_service
from records.models import MatchRecordOut, MatchRecordPageOut, MatchSide, RecordedMatch

_AT = datetime(2026, 11, 3, 0, 41, tzinfo=timezone.utc)


@pytest.fixture
def client_and_service():
    from app import app

    service = AsyncMock()
    service.list_matches.return_value = MatchRecordPageOut(matches=[], next_before=None)
    app.dependency_overrides[records_service] = lambda: service
    yield TestClient(app), service  # no `with`: lifespan stays off, the service is ours
    app.dependency_overrides.pop(records_service)


def test_passes_the_filters_and_the_page_through(client_and_service):
    client, service = client_and_service
    response = client.get("/records/matches", params={"npid": "alice", "q": "bo", "before": 90, "limit": 5})
    assert response.status_code == 200
    service.list_matches.assert_awaited_once_with("alice", "bo", 90, 5)


def test_asks_for_twenty_from_the_newest_by_default(client_and_service):
    client, service = client_and_service
    client.get("/records/matches")
    service.list_matches.assert_awaited_once_with(None, None, None, 20)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"before": 0}, {"q": ""}, {"q": "x" * 33}])
def test_refuses_a_page_or_search_out_of_range(client_and_service, params):
    client, service = client_and_service
    assert client.get("/records/matches", params=params).status_code == 422
    service.list_matches.assert_not_awaited()


def test_a_match_answers_names_and_ranks_and_says_what_was_not_seen():
    winner = MatchSide("alice", "Alice", (0, 9), (20, 99))
    loser = MatchSide("bob", None, None, None)
    out = MatchRecordOut.of(RecordedMatch(7, _AT, winner, loser)).model_dump()

    assert out["winner"]["chars"] == [
        {"name": "Paul", "rank": {"name": "Berserker", "tier": "녹단"}},
        # A rank code the table does not know answers no rank rather than failing the list.
        {"name": "Jin", "rank": None},
    ]
    assert out["loser"] == {"npid": "bob", "online_name": None, "chars": None}


def test_a_match_recorded_before_ranks_answers_characters_without_them():
    side = MatchSide("alice", "Alice", (0,), None)
    out = MatchRecordOut.of(RecordedMatch(7, _AT, side, None)).model_dump()

    assert out["winner"]["chars"] == [{"name": "Paul", "rank": None}]
    assert out["loser"] is None
