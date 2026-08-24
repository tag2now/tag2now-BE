"""Replaceable infrastructure contracts for reservations."""

from abc import ABC, abstractmethod
from datetime import date, datetime

from reservation.domain import MatchType, Participant, Reservation


class ReservationRepository(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def list_for_date(self, day: date) -> list[Reservation]: ...

    @abstractmethod
    async def get(self, reservation_id: int) -> Reservation: ...

    @abstractmethod
    async def create(self, *, start_at: datetime, duration_minutes: int, host_display_name: str, host_ranks: list[str], match_type: MatchType, capacity: int, memo: str, host_token_hash: str) -> Reservation: ...

    @abstractmethod
    async def join(self, reservation_id: int, *, display_name: str, ranks: list[str], participant_token_hash: str, now: datetime) -> tuple[Reservation, Participant]: ...

    @abstractmethod
    async def cancel_participation(self, reservation_id: int, participant_token_hash: str, now: datetime) -> Reservation: ...

    @abstractmethod
    async def cancel(self, reservation_id: int, host_token_hash: str, now: datetime) -> None: ...


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...
