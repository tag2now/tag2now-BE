"""HTTP request and response DTOs; separate from domain entities."""

from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reservation.domain import MatchType, ReservationStatus


def _reject_duplicate_ranks(ranks: list[str] | None) -> list[str] | None:
    if ranks is not None and len(set(ranks)) != len(ranks):
        raise ValueError("같은 계급을 중복해서 선택할 수 없습니다.")
    return ranks


class CreateReservationRequest(BaseModel):
    """The host is the signed-in user; nothing here names them."""

    start_time: time
    ranks: list[str] = Field(default_factory=list, max_length=20)
    match_type: MatchType
    capacity: int = Field(1, ge=1, le=3)
    memo: str = Field("", max_length=140)

    _check_ranks = field_validator("ranks")(_reject_duplicate_ranks)


class UpdateReservationRequest(BaseModel):
    """Every field optional: the host sends only what changed.

    The validators are the create request's own, so a rule cannot drift between
    posting a reservation and editing one.
    """

    start_time: time | None = None
    ranks: list[str] | None = Field(None, max_length=20)
    match_type: MatchType | None = None
    capacity: int | None = Field(None, ge=1, le=3)
    memo: str | None = Field(None, max_length=140)

    _check_ranks = field_validator("ranks")(_reject_duplicate_ranks)


class JoinReservationRequest(BaseModel):
    ranks: list[str] = Field(default_factory=list, max_length=20)


class CreateCommentRequest(BaseModel):
    """Whitespace is stripped before the length rules run.

    A body of three spaces is an empty comment; letting min_length see it
    unstripped would store one, because the service strips on the way to the
    repository either way.
    """

    body: str = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class CommentOut(BaseModel):
    id: int
    reservation_id: int
    author: str
    # Compared against /auth/me to decide whether to offer deletion. Null on
    # comments from before login, which nobody can delete any more.
    author_username: str | None
    body: str
    created_at: datetime


class ParticipantSummaryOut(BaseModel):
    id: int
    display_name: str
    username: str | None


class ReservationOut(BaseModel):
    id: int
    start_at: datetime
    host_display_name: str
    host_username: str | None
    host_ranks: list[str]
    match_type: MatchType
    capacity: int
    memo: str
    status: ReservationStatus
    participant_count: int
    participants: list[ParticipantSummaryOut]
    created_at: datetime
