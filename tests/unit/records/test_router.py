"""GET /records/matches and /records/weekly-top: their queries, and the shapes they answer in."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from records.dependencies import records_service
from records.models import MatchOutcome, MatchRecordOut, MatchRecordPageOut, MatchPlayer, RecordedMatch, WeeklyPlayer

_AT = datetime(2026, 11, 3, 0, 41, tzinfo=timezone.utc)


@pytest.fixture
def client_and_service():
    from app import app

    service = AsyncMock()
    service.list_matches.return_value = MatchRecordPageOut(matches=[], next_before=None)
    service.weekly_top_players.return_value = [WeeklyPlayer("alice", "Alice", 3, 2, 1)]
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
    p1 = MatchPlayer("alice", "Alice", MatchOutcome.WIN, (0, 9), (20, 99))
    p2 = MatchPlayer("bob", None, MatchOutcome.LOSS, None, None)
    out = MatchRecordOut.of(RecordedMatch(7, _AT, p1, p2)).model_dump()

    assert out["p1"]["result"] == "win"
    assert out["p1"]["chars"] == [
        {"name": "Paul", "rank": {"name": "Berserker", "tier": "녹단"}},
        # A rank code the table does not know answers no rank rather than failing the list.
        {"name": "Jin", "rank": None},
    ]
    assert out["p2"] == {"npid": "bob", "online_name": None, "result": "loss", "chars": None}


def test_a_match_recorded_before_ranks_answers_characters_without_them():
    side = MatchPlayer("alice", "Alice", MatchOutcome.WIN, (0,), None)
    out = MatchRecordOut.of(RecordedMatch(7, _AT, side, None)).model_dump()

    assert out["p1"]["chars"] == [{"name": "Paul", "rank": None}]
    assert out["p2"] is None


def test_the_weekly_top_answers_ten_players_with_their_wins_and_losses(client_and_service):
    client, service = client_and_service
    response = client.get("/records/weekly-top")
    assert response.json() == [{"npid": "alice", "online_name": "Alice", "match_count": 3, "wins": 2, "losses": 1}]
    service.weekly_top_players.assert_awaited_once_with(10)


@pytest.mark.parametrize("limit", [0, 51])
def test_refuses_a_weekly_top_out_of_range(client_and_service, limit):
    client, service = client_and_service
    assert client.get("/records/weekly-top", params={"limit": limit}).status_code == 422
    service.weekly_top_players.assert_not_awaited()
