"""Replaceable infrastructure contracts for reservations."""

from abc import ABC, abstractmethod
from datetime import datetime

from reservation.domain import Comment, MatchType, Participant, Reservation


class ReservationRepository(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def list_upcoming(self) -> list[Reservation]: ...

    @abstractmethod
    async def get(self, reservation_id: int) -> Reservation: ...

    @abstractmethod
    async def create(self, *, start_at: datetime, host_display_name: str, host_ranks: list[str], match_type: MatchType, capacity: int, memo: str, host_token_hash: str) -> Reservation: ...

    @abstractmethod
    async def update(self, reservation_id: int, host_token_hash: str, now: datetime, *, start_at: datetime | None = None, ranks: list[str] | None = None, match_type: MatchType | None = None, capacity: int | None = None, memo: str | None = None) -> Reservation: ...

    @abstractmethod
    async def join(self, reservation_id: int, *, display_name: str, ranks: list[str], participant_token_hash: str, now: datetime) -> tuple[Reservation, Participant]: ...

    @abstractmethod
    async def cancel_participation(self, reservation_id: int, participant_token_hash: str, now: datetime) -> Reservation: ...

    @abstractmethod
    async def cancel(self, reservation_id: int, host_token_hash: str, now: datetime) -> None: ...

    @abstractmethod
    async def list_comments(self, reservation_id: int) -> list[Comment]: ...

    @abstractmethod
    async def add_comment(self, reservation_id: int, *, author: str, body: str, author_token_hash: str) -> Comment: ...

    @abstractmethod
    async def delete_comment(self, reservation_id: int, comment_id: int, author_token_hash: str, now: datetime) -> None: ...


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...
