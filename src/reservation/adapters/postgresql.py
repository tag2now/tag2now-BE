"""SQLAlchemy ORM adapter. Row locking keeps participant capacity atomic."""

from datetime import datetime, timezone

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reservation.domain import (
    LISTING_GRACE, LIVE_STATUSES, Comment, MatchType, Participant, ParticipantSummary, Reservation, ReservationStatus,
    ensure_commentable, ensure_editable, ensure_joinable, ensure_participation_cancellable,
    status_for, window_end,
)
from reservation.entities import Reservation as ReservationRow
from reservation.entities import ReservationComment as ReservationCommentRow
from reservation.entities import ReservationParticipant as ReservationParticipantRow
from reservation.exceptions import ReservationAccessError, ReservationNotFoundError, ReservationStateError
from reservation.ports import ReservationRepository
from shared.database import get_session_factory



def _comment(row: ReservationCommentRow) -> Comment:
    return Comment(
        id=row.id, reservation_id=row.reservation_id, author=row.author,
        body=row.body, created_at=row.created_at, author_username=row.author_subject,
    )


def _reservation(row: ReservationRow, participant_count: int, participants: list[dict] | None = None) -> Reservation:
    return Reservation(
        id=row.id, start_at=row.start_at,
        host_display_name=row.host_display_name, host_ranks=list(row.host_ranks),
        match_type=MatchType(row.match_type), capacity=row.capacity, memo=row.memo,
        status=ReservationStatus(row.status), participant_count=participant_count,
        created_at=row.created_at,
        participants=[ParticipantSummary(**item) for item in (participants or [])],
        host_username=row.host_subject,
    )


class PostgresReservationRepository(ReservationRepository):
    """Reservation persistence using the application's shared session factory."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None):
        self._session_factory = session_factory

    async def init(self) -> None:
        self._session_factory = self._session_factory or get_session_factory()

    async def close(self) -> None:
        """The shared database lifecycle owns the engine."""

    @property
    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Reservation repository not initialized")
        return self._session_factory

    @staticmethod
    def _with_participant_count():
        count = func.count(ReservationParticipantRow.id).label("participant_count")
        participants = func.json_agg(aggregate_order_by(
            func.json_build_object(
                "id", ReservationParticipantRow.id,
                "display_name", ReservationParticipantRow.display_name,
                "username", ReservationParticipantRow.subject,
            ),
            ReservationParticipantRow.joined_at, ReservationParticipantRow.id,
        )).filter(ReservationParticipantRow.id.is_not(None)).label("participants")
        return (
            select(ReservationRow, count, participants)
            .outerjoin(
                ReservationParticipantRow,
                (ReservationParticipantRow.reservation_id == ReservationRow.id)
                & ReservationParticipantRow.cancelled_at.is_(None),
            )
            .group_by(ReservationRow.id)
        )

    @staticmethod
    def _finished(now: datetime):
        """Rows whose grace hour past the start has already run out."""
        return (ReservationRow.status.in_(LIVE_STATUSES), ReservationRow.start_at <= now - LISTING_GRACE)

    @classmethod
    async def _expire_finished(cls, session: AsyncSession, now: datetime) -> None:
        """Retire reservations whose time has passed, in two statements.

        Deliberately unbounded by the requested date — a reservation from any
        day must be retired once it ends. Doing it per row would make a listing
        cost grow with the table, and the rooms tab polls this every 10s.
        """
        finished = cls._finished(now)
        await session.execute(
            update(ReservationParticipantRow)
            .where(
                ReservationParticipantRow.cancelled_at.is_(None),
                ReservationParticipantRow.reservation_id.in_(
                    select(ReservationRow.id).where(*finished)
                ),
            )
            .values(cancelled_at=now)
        )
        await session.execute(
            update(ReservationRow)
            .where(*finished)
            .values(status=ReservationStatus.ENDED.value, ended_at=now, updated_at=now)
        )

    @staticmethod
    async def _active_participant_count(session: AsyncSession, reservation_id: int) -> int:
        return await session.scalar(
            select(func.count()).select_from(ReservationParticipantRow).where(
                ReservationParticipantRow.reservation_id == reservation_id,
                ReservationParticipantRow.cancelled_at.is_(None),
            )
        ) or 0

    @staticmethod
    async def _active_participation(session: AsyncSession, reservation_id: int, subject: str) -> ReservationParticipantRow | None:
        return await session.scalar(
            select(ReservationParticipantRow).where(
                ReservationParticipantRow.reservation_id == reservation_id,
                ReservationParticipantRow.subject == subject,
                ReservationParticipantRow.cancelled_at.is_(None),
            )
        )

    @staticmethod
    async def _release_participants(session: AsyncSession, reservation_id: int, now: datetime) -> None:
        """A reservation that stops being live carries no active participants."""
        await session.execute(
            update(ReservationParticipantRow)
            .where(
                ReservationParticipantRow.reservation_id == reservation_id,
                ReservationParticipantRow.cancelled_at.is_(None),
            )
            .values(cancelled_at=now)
        )

    async def list_upcoming(self) -> list[Reservation]:
        """Everything from an hour ago up to the next 06:00 KST.

        The window is anchored to now rather than to a date. It reaches an hour
        back because a reservation that has just started is not over — the
        players are in it, and the listing is the only route to its detail page,
        so dropping it at the stroke of its start time would strand them.
        """
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            await self._expire_finished(session, now)
            result = await session.execute(
                self._with_participant_count()
                .where(
                    ReservationRow.start_at > now - LISTING_GRACE,
                    ReservationRow.start_at < window_end(now),
                    ReservationRow.status.in_(("open", "matched")),
                )
                .order_by(ReservationRow.start_at, case((ReservationRow.status == "open", 0), else_=1))
            )
            return [_reservation(*item) for item in result.all()]

    async def get(self, reservation_id: int) -> Reservation:
        async with self._sessions() as session:
            result = await session.execute(self._with_participant_count().where(ReservationRow.id == reservation_id))
            found = result.one_or_none()
            if found is None:
                raise ReservationNotFoundError("Reservation not found")
            return _reservation(*found)

    async def create(self, **values) -> Reservation:
        async with self._sessions() as session, session.begin():
            row = ReservationRow(
                start_at=values["start_at"], host_subject=values["host_subject"],
                host_display_name=values["host_display_name"], host_ranks=values["host_ranks"],
                match_type=values["match_type"].value,
                capacity=values["capacity"], memo=values["memo"],
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _reservation(row, 0)

    async def update(self, reservation_id: int, host_subject: str, now: datetime, **changes) -> Reservation:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update())
            if row is None:
                raise ReservationNotFoundError("Reservation not found")
            if row.host_subject is None or row.host_subject != host_subject:
                raise ReservationAccessError("예약한 사람만 수정할 수 있습니다.")
            count = await self._active_participant_count(session, reservation_id)
            ensure_editable(ReservationStatus(row.status), row.start_at, count, now)

            applied = {field: value for field, value in changes.items() if value is not None}
            if "match_type" in applied:
                applied["match_type"] = applied["match_type"].value
            if "ranks" in applied:
                applied["host_ranks"] = applied.pop("ranks")
            for field, value in applied.items():
                setattr(row, field, value)
            row.updated_at = now
            await session.flush()
            await session.refresh(row)
            return _reservation(row, count)

    async def join(self, reservation_id: int, *, subject: str, display_name: str, ranks: list[str], now: datetime) -> tuple[Reservation, Participant]:
        try:
            return await self._join(reservation_id, subject=subject, display_name=display_name, ranks=ranks, now=now)
        except IntegrityError as exc:
            # The row lock serialises joins to one reservation, so the check
            # below normally answers first; the unique index is the backstop.
            raise ReservationStateError("이미 참가한 예약입니다.") from exc

    async def _join(self, reservation_id: int, *, subject: str, display_name: str, ranks: list[str], now: datetime) -> tuple[Reservation, Participant]:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update())
            if row is None:
                raise ReservationNotFoundError("Reservation not found")
            count = await session.scalar(
                select(func.count()).select_from(ReservationParticipantRow).where(
                    ReservationParticipantRow.reservation_id == reservation_id,
                    ReservationParticipantRow.cancelled_at.is_(None),
                )
            )
            if row.host_subject == subject:
                raise ReservationStateError("내가 만든 예약에는 참가할 수 없습니다.")
            if await self._active_participation(session, reservation_id, subject) is not None:
                raise ReservationStateError("이미 참가한 예약입니다.")
            ensure_joinable(ReservationStatus(row.status), row.start_at, count, row.capacity, now)
            participant = ReservationParticipantRow(
                reservation_id=reservation_id, subject=subject, display_name=display_name, ranks=ranks,
            )
            session.add(participant)
            count += 1
            row.status = status_for(count, row.capacity).value
            row.updated_at = now
            await session.flush()
            await session.refresh(participant)
            result = await session.execute(self._with_participant_count().where(ReservationRow.id == reservation_id))
            return _reservation(*result.one()), Participant(
                id=participant.id, reservation_id=reservation_id,
                display_name=participant.display_name, ranks=list(participant.ranks),
                joined_at=participant.joined_at,
            )

    async def cancel_participation(self, reservation_id: int, subject: str, now: datetime) -> Reservation:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update())
            if row is None:
                raise ReservationNotFoundError("Reservation not found")
            ensure_participation_cancellable(ReservationStatus(row.status), row.start_at, now)
            participant = await self._active_participation(session, reservation_id, subject)
            if participant is None:
                raise ReservationAccessError("참가 중인 예약이 아닙니다.")
            participant.cancelled_at = now
            await session.flush()
            count = await session.scalar(
                select(func.count()).select_from(ReservationParticipantRow).where(
                    ReservationParticipantRow.reservation_id == reservation_id,
                    ReservationParticipantRow.cancelled_at.is_(None),
                )
            )
            row.status, row.updated_at = status_for(count, row.capacity).value, now
            await session.flush()
            result = await session.execute(self._with_participant_count().where(ReservationRow.id == reservation_id))
            return _reservation(*result.one())

    async def list_comments(self, reservation_id: int) -> list[Comment]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ReservationCommentRow)
                .where(
                    ReservationCommentRow.reservation_id == reservation_id,
                    ReservationCommentRow.deleted_at.is_(None),
                )
                .order_by(ReservationCommentRow.created_at, ReservationCommentRow.id)
            )
            return [_comment(row) for row in rows]

    async def add_comment(self, reservation_id: int, *, author_subject: str, author: str, body: str) -> Comment:
        async with self._sessions() as session, session.begin():
            reservation = await session.get(ReservationRow, reservation_id)
            if reservation is None:
                raise ReservationNotFoundError("Reservation not found")
            ensure_commentable(ReservationStatus(reservation.status))
            row = ReservationCommentRow(
                reservation_id=reservation_id, author_subject=author_subject, author=author, body=body,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _comment(row)

    async def delete_comment(self, reservation_id: int, comment_id: int, author_subject: str, now: datetime) -> None:
        """Soft delete, so a reply reading as an answer to nothing is at least rare.

        The row is kept rather than removed because the listing is ordered by
        creation and people quote each other; a hole is easier to read than a
        renumbered thread.
        """
        async with self._sessions() as session, session.begin():
            row = await session.get(ReservationCommentRow, comment_id)
            if row is None or row.reservation_id != reservation_id or row.deleted_at is not None:
                raise ReservationNotFoundError("Comment not found")
            if row.author_subject is None or row.author_subject != author_subject:
                raise ReservationAccessError("작성한 사람만 삭제할 수 있습니다.")
            row.deleted_at = now

    async def cancel(self, reservation_id: int, host_subject: str, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update())
            if row is None:
                raise ReservationNotFoundError("Reservation not found")
            if row.host_subject is None or row.host_subject != host_subject:
                raise ReservationAccessError("예약한 사람만 취소할 수 있습니다.")
            if row.status not in LIVE_STATUSES or row.start_at <= now:
                raise ReservationAccessError("이미 시작했거나 끝난 예약은 취소할 수 없습니다.")
            row.status, row.cancelled_at, row.updated_at = "cancelled", now, now
            await self._release_participants(session, reservation_id, now)
