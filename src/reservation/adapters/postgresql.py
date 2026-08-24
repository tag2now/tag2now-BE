"""SQLAlchemy ORM adapter. Row locking keeps participant capacity atomic."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reservation.domain import MatchType, Participant, Reservation, ReservationStatus
from reservation.entities import Reservation as ReservationRow
from reservation.entities import ReservationParticipant as ReservationParticipantRow
from reservation.exceptions import ReservationAccessError, ReservationNotFoundError, ReservationStateError
from reservation.ports import ReservationRepository
from shared.database import get_session_factory

KST = ZoneInfo("Asia/Seoul")


def _reservation(row: ReservationRow, participant_count: int) -> Reservation:
    return Reservation(
        id=row.id, start_at=row.start_at, duration_minutes=row.duration_minutes,
        host_display_name=row.host_display_name, host_ranks=list(row.host_ranks),
        match_type=MatchType(row.match_type), capacity=row.capacity, memo=row.memo,
        status=ReservationStatus(row.status), participant_count=participant_count,
        created_at=row.created_at,
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
        return (
            select(ReservationRow, count)
            .outerjoin(
                ReservationParticipantRow,
                (ReservationParticipantRow.reservation_id == ReservationRow.id)
                & ReservationParticipantRow.cancelled_at.is_(None),
            )
            .group_by(ReservationRow.id)
        )

    async def list_for_date(self, day: date) -> list[Reservation]:
        start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
        end = start + timedelta(days=1)
        now = datetime.now(timezone.utc)
        async with self._sessions() as session, session.begin():
            stale = await session.scalars(
                select(ReservationRow).where(ReservationRow.status.in_(("open", "matched")))
            )
            for row in stale:
                if row.start_at + timedelta(minutes=row.duration_minutes) <= now:
                    row.status, row.ended_at, row.updated_at = "ended", now, now
            result = await session.execute(
                self._with_participant_count()
                .where(
                    ReservationRow.start_at >= start,
                    ReservationRow.start_at < end,
                    ReservationRow.status.in_(("open", "matched")),
                )
                .order_by(ReservationRow.start_at, case((ReservationRow.status == "open", 0), else_=1))
            )
            return [_reservation(row, count) for row, count in result.all()]

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
                start_at=values["start_at"], duration_minutes=values["duration_minutes"],
                host_display_name=values["host_display_name"], host_ranks=values["host_ranks"],
                host_token_hash=values["host_token_hash"], match_type=values["match_type"].value,
                capacity=values["capacity"], memo=values["memo"],
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _reservation(row, 0)

    async def join(self, reservation_id: int, *, display_name: str, ranks: list[str], participant_token_hash: str, now: datetime) -> tuple[Reservation, Participant]:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update())
            if row is None:
                raise ReservationNotFoundError("Reservation not found")
            if row.status != "open" or row.start_at <= now:
                raise ReservationStateError("Reservation is not open for joining")
            count = await session.scalar(
                select(func.count()).select_from(ReservationParticipantRow).where(
                    ReservationParticipantRow.reservation_id == reservation_id,
                    ReservationParticipantRow.cancelled_at.is_(None),
                )
            )
            if count >= row.capacity:
                raise ReservationStateError("Reservation is full")
            participant = ReservationParticipantRow(
                reservation_id=reservation_id, display_name=display_name, ranks=ranks,
                participant_token_hash=participant_token_hash,
            )
            session.add(participant)
            count += 1
            row.status = "matched" if count == row.capacity else "open"
            row.updated_at = now
            await session.flush()
            await session.refresh(participant)
            return _reservation(row, count), Participant(
                id=participant.id, reservation_id=reservation_id,
                display_name=participant.display_name, ranks=list(participant.ranks),
                joined_at=participant.joined_at,
            )

    async def cancel_participation(self, reservation_id: int, participant_token_hash: str, now: datetime) -> Reservation:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update())
            if row is None:
                raise ReservationNotFoundError("Reservation not found")
            if row.start_at <= now:
                raise ReservationStateError("Reservation has started")
            participant = await session.scalar(
                select(ReservationParticipantRow).where(
                    ReservationParticipantRow.reservation_id == reservation_id,
                    ReservationParticipantRow.participant_token_hash == participant_token_hash,
                    ReservationParticipantRow.cancelled_at.is_(None),
                )
            )
            if participant is None:
                raise ReservationAccessError("Active participation not found")
            participant.cancelled_at = now
            row.status, row.updated_at = "open", now
            count = await session.scalar(
                select(func.count()).select_from(ReservationParticipantRow).where(
                    ReservationParticipantRow.reservation_id == reservation_id,
                    ReservationParticipantRow.cancelled_at.is_(None),
                )
            )
            return _reservation(row, count)

    async def cancel(self, reservation_id: int, host_token_hash: str, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(ReservationRow).where(ReservationRow.id == reservation_id).with_for_update())
            if row is None:
                raise ReservationNotFoundError("Reservation not found")
            if row.host_token_hash != host_token_hash or row.status not in ("open", "matched") or row.start_at <= now:
                raise ReservationAccessError("Reservation cannot be cancelled with this credential")
            row.status, row.cancelled_at, row.updated_at = "cancelled", now, now
