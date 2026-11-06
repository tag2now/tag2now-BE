"""Replaceable infrastructure contracts for reservations.

Every method runs in the session the service passes, so the service decides the
transaction.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from reservation.domain import Comment, MatchType, Participant, Reservation


class ReservationRepository(ABC):
    @abstractmethod
    async def list_upcoming(self, session: AsyncSession) -> list[Reservation]: ...

    @abstractmethod
    async def get(self, session: AsyncSession, reservation_id: int) -> Reservation: ...

    @abstractmethod
    async def create(
        self,
        session: AsyncSession,
        *,
        start_at: datetime,
        host_subject: str,
        host_display_name: str,
        host_ranks: list[str],
        match_type: MatchType,
        capacity: int,
        memo: str,
    ) -> Reservation: ...

    @abstractmethod
    async def update(
        self,
        session: AsyncSession,
        reservation_id: int,
        host_subject: str,
        now: datetime,
        *,
        start_at: datetime | None = None,
        ranks: list[str] | None = None,
        match_type: MatchType | None = None,
        capacity: int | None = None,
        memo: str | None = None,
    ) -> Reservation: ...

    @abstractmethod
    async def join(
        self,
        session: AsyncSession,
        reservation_id: int,
        *,
        subject: str,
        display_name: str,
        ranks: list[str],
        now: datetime,
    ) -> tuple[Reservation, Participant]: ...

    @abstractmethod
    async def cancel_participation(
        self, session: AsyncSession, reservation_id: int, subject: str, now: datetime
    ) -> Reservation: ...

    @abstractmethod
    async def cancel(self, session: AsyncSession, reservation_id: int, host_subject: str, now: datetime) -> None: ...

    @abstractmethod
    async def list_comments(self, session: AsyncSession, reservation_id: int) -> list[Comment]: ...

    @abstractmethod
    async def add_comment(
        self, session: AsyncSession, reservation_id: int, *, author_subject: str, author: str, body: str
    ) -> Comment: ...

    @abstractmethod
    async def delete_comment(
        self, session: AsyncSession, reservation_id: int, comment_id: int, subject: str, now: datetime, *, admin: bool
    ) -> None: ...
