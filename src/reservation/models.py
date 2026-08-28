"""HTTP request and response DTOs; separate from domain entities."""

from datetime import datetime, time

from pydantic import BaseModel, Field, field_validator

from reservation.domain import MatchType, ReservationStatus


SUPPORTED_DURATIONS = {30, 60, 120, 180}


def _reject_duplicate_ranks(ranks: list[str] | None) -> list[str] | None:
    if ranks is not None and len(set(ranks)) != len(ranks):
        raise ValueError("ranks must not contain duplicates")
    return ranks


def _reject_unsupported_duration(minutes: int | None) -> int | None:
    if minutes is not None and minutes not in SUPPORTED_DURATIONS:
        raise ValueError("duration_minutes must be 30, 60, 120, or 180")
    return minutes


class CreateReservationRequest(BaseModel):
    start_time: time
    duration_minutes: int = Field(..., ge=30, le=240)
    display_name: str = Field(..., min_length=1, max_length=50)
    ranks: list[str] = Field(default_factory=list, max_length=20)
    match_type: MatchType
    capacity: int = Field(1, ge=1, le=3)
    memo: str = Field("", max_length=140)

    _check_ranks = field_validator("ranks")(_reject_duplicate_ranks)
    _check_duration = field_validator("duration_minutes")(_reject_unsupported_duration)


class UpdateReservationRequest(BaseModel):
    """Every field optional: the host sends only what changed.

    The validators are the create request's own, so a rule cannot drift between
    posting a reservation and editing one.
    """

    start_time: time | None = None
    duration_minutes: int | None = Field(None, ge=30, le=240)
    ranks: list[str] | None = Field(None, max_length=20)
    match_type: MatchType | None = None
    capacity: int | None = Field(None, ge=1, le=3)
    memo: str | None = Field(None, max_length=140)

    _check_ranks = field_validator("ranks")(_reject_duplicate_ranks)
    _check_duration = field_validator("duration_minutes")(_reject_unsupported_duration)


class JoinReservationRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)
    ranks: list[str] = Field(default_factory=list, max_length=20)


class ReservationOut(BaseModel):
    id: int
    start_at: datetime
    duration_minutes: int
    host_display_name: str
    host_ranks: list[str]
    match_type: MatchType
    capacity: int
    memo: str
    status: ReservationStatus
    participant_count: int
    created_at: datetime


class CreateReservationOut(BaseModel):
    reservation: ReservationOut
    owner_token: str


class JoinReservationOut(BaseModel):
    reservation: ReservationOut
    participant_token: str
