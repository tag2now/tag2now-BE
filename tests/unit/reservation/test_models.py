from datetime import time

import pytest
from pydantic import ValidationError

from reservation.domain import MatchType
from reservation.models import CreateReservationRequest


def _request(**overrides):
    values = {
        "start_time": time(20, 0), "duration_minutes": 60, "display_name": "Host",
        "ranks": ["Brawler"], "match_type": MatchType.RANK, "capacity": 1, "memo": "",
    }
    values.update(overrides)
    return CreateReservationRequest(**values)


@pytest.mark.parametrize("duration", [31, 90, 240])
def test_create_request_rejects_unsupported_durations(duration):
    with pytest.raises(ValidationError, match="duration_minutes"):
        _request(duration_minutes=duration)


def test_create_request_rejects_duplicate_ranks():
    with pytest.raises(ValidationError, match="ranks"):
        _request(ranks=["Brawler", "Brawler"])
