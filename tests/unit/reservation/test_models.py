from datetime import time

import pytest
from pydantic import ValidationError

from reservation.domain import MatchType
from reservation.models import CreateReservationRequest


def _request(**overrides):
    values = {
        "start_time": time(20, 0),
        "ranks": ["Brawler"], "match_type": MatchType.RANK, "capacity": 1, "memo": "",
    }
    values.update(overrides)
    return CreateReservationRequest(**values)


def test_create_request_rejects_duplicate_ranks():
    with pytest.raises(ValidationError, match="ranks"):
        _request(ranks=["Brawler", "Brawler"])


def test_participant_response_exposes_the_name_and_username_only():
    """The username is public --- it is the RPCN id the leaderboard shows --- and
    it is how the client recognises its own seat. Ranks stay private."""
    from reservation.models import ParticipantSummaryOut

    response = ParticipantSummaryOut.model_validate({
        "id": 7, "display_name": "Joiner", "username": "joiner", "ranks": ["Brawler"],
    })
    assert response.model_dump() == {"id": 7, "display_name": "Joiner", "username": "joiner"}
