"""HTTP request and response DTOs; separate from domain entities."""

from datetime import datetime, time

from pydantic import BaseModel, Field, field_validator

from reservation.domain import MatchType, ReservationStatus


class CreateReservationRequest(BaseModel):
    start_time: time
    duration_minutes: int = Field(..., ge=30, le=240)
    display_name: str = Field(..., min_length=1, max_length=50)
    ranks: list[str] = Field(default_factory=list, max_length=20)
    match_type: MatchType
    capacity: int = Field(1, ge=1, le=3)
    memo: str = Field("", max_length=140)

    @field_validator("ranks")
    @classmethod
    def no_duplicate_ranks(cls, ranks: list[str]) -> list[str]:
        if len(set(ranks)) != len(ranks):
            raise ValueError("ranks must not contain duplicates")
        return ranks

    @field_validator("duration_minutes")
    @classmethod
    def must_be_supported_duration(cls, minutes: int) -> int:
        if minutes not in {30, 60, 120, 180}:
            raise ValueError("duration_minutes must be 30, 60, 120, or 180")
        return minutes


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
