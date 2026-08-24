"""PostgreSQL adapter. Row locking makes participant capacity atomic."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg

from reservation.domain import MatchType, Participant, Reservation, ReservationStatus
from reservation.exceptions import ReservationAccessError, ReservationNotFoundError, ReservationStateError
from reservation.ports import ReservationRepository

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        start_at TIMESTAMPTZ NOT NULL, duration_minutes INTEGER NOT NULL,
        host_display_name TEXT NOT NULL, host_subject TEXT, host_ranks TEXT[] NOT NULL DEFAULT '{}',
        host_token_hash TEXT NOT NULL, match_type TEXT NOT NULL,
        capacity INTEGER NOT NULL, memo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        cancelled_at TIMESTAMPTZ, ended_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS reservation_participants (
        id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
        display_name TEXT NOT NULL, subject TEXT, ranks TEXT[] NOT NULL DEFAULT '{}', participant_token_hash TEXT NOT NULL,
        joined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, cancelled_at TIMESTAMPTZ,
        UNIQUE(reservation_id, participant_token_hash)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_reservations_start_at ON reservations(start_at)",
    "CREATE INDEX IF NOT EXISTS idx_reservation_participants_active ON reservation_participants(reservation_id) WHERE cancelled_at IS NULL",
]
KST = ZoneInfo("Asia/Seoul")


def _reservation(row: asyncpg.Record) -> Reservation:
    return Reservation(id=row["id"], start_at=row["start_at"], duration_minutes=row["duration_minutes"], host_display_name=row["host_display_name"], host_ranks=list(row["host_ranks"]), match_type=MatchType(row["match_type"]), capacity=row["capacity"], memo=row["memo"], status=ReservationStatus(row["status"]), participant_count=row["participant_count"], created_at=row["created_at"])


class PostgresReservationRepository(ReservationRepository):
    def __init__(self, dsn: str): self._dsn, self._pool = dsn, None

    async def init(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        async with self._pool.acquire() as conn:
            for statement in _SCHEMA: await conn.execute(statement)

    async def close(self) -> None:
        if self._pool: await self._pool.close(); self._pool = None

    @property
    def _db(self):
        if self._pool is None: raise RuntimeError("Reservation repository not initialized")
        return self._pool

    async def list_for_date(self, day: date) -> list[Reservation]:
        start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
        end = start + timedelta(days=1)
        await self._db.execute("""UPDATE reservations SET status='ended', ended_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE status IN ('open','matched') AND start_at + (duration_minutes * INTERVAL '1 minute') <= CURRENT_TIMESTAMP""")
        rows = await self._db.fetch("""SELECT r.*, COUNT(p.id)::int participant_count FROM reservations r
            LEFT JOIN reservation_participants p ON p.reservation_id=r.id AND p.cancelled_at IS NULL
            WHERE r.start_at >= $1 AND r.start_at < $2 AND r.status IN ('open','matched')
            GROUP BY r.id ORDER BY r.start_at, CASE r.status WHEN 'open' THEN 0 ELSE 1 END""", start, end)
        return [_reservation(row) for row in rows]

    async def get(self, reservation_id: int) -> Reservation:
        row = await self._db.fetchrow("""SELECT r.*, COUNT(p.id)::int participant_count FROM reservations r
            LEFT JOIN reservation_participants p ON p.reservation_id=r.id AND p.cancelled_at IS NULL WHERE r.id=$1 GROUP BY r.id""", reservation_id)
        if row is None: raise ReservationNotFoundError("Reservation not found")
        return _reservation(row)

    async def create(self, **values) -> Reservation:
        row = await self._db.fetchrow("""INSERT INTO reservations (start_at,duration_minutes,host_display_name,host_ranks,host_token_hash,match_type,capacity,memo)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *, 0::int participant_count""", values["start_at"], values["duration_minutes"], values["host_display_name"], values["host_ranks"], values["host_token_hash"], values["match_type"].value, values["capacity"], values["memo"])
        return _reservation(row)

    async def join(self, reservation_id: int, *, display_name: str, ranks: list[str], participant_token_hash: str, now: datetime) -> tuple[Reservation, Participant]:
        async with self._db.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT * FROM reservations WHERE id=$1 FOR UPDATE", reservation_id)
                if row is None: raise ReservationNotFoundError("Reservation not found")
                if row["status"] != "open" or row["start_at"] <= now: raise ReservationStateError("Reservation is not open for joining")
                count = await conn.fetchval("SELECT COUNT(*) FROM reservation_participants WHERE reservation_id=$1 AND cancelled_at IS NULL", reservation_id)
                if count >= row["capacity"]: raise ReservationStateError("Reservation is full")
                participant = await conn.fetchrow("""INSERT INTO reservation_participants (reservation_id,display_name,ranks,participant_token_hash)
                    VALUES ($1,$2,$3,$4) RETURNING *""", reservation_id, display_name, ranks, participant_token_hash)
                count += 1
                status = "matched" if count == row["capacity"] else "open"
                await conn.execute("UPDATE reservations SET status=$1, updated_at=CURRENT_TIMESTAMP WHERE id=$2", status, reservation_id)
                updated = dict(row); updated["status"] = status; updated["participant_count"] = count
                return _reservation(updated), Participant(id=participant["id"], reservation_id=reservation_id, display_name=participant["display_name"], ranks=list(participant["ranks"]), joined_at=participant["joined_at"])

    async def cancel_participation(self, reservation_id: int, participant_token_hash: str, now: datetime) -> Reservation:
        async with self._db.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT * FROM reservations WHERE id=$1 FOR UPDATE", reservation_id)
                if row is None: raise ReservationNotFoundError("Reservation not found")
                if row["start_at"] <= now: raise ReservationStateError("Reservation has started")
                participant = await conn.fetchrow("""UPDATE reservation_participants SET cancelled_at=$1 WHERE reservation_id=$2 AND participant_token_hash=$3 AND cancelled_at IS NULL RETURNING id""", now, reservation_id, participant_token_hash)
                if participant is None: raise ReservationAccessError("Active participation not found")
                count = await conn.fetchval("SELECT COUNT(*) FROM reservation_participants WHERE reservation_id=$1 AND cancelled_at IS NULL", reservation_id)
                await conn.execute("UPDATE reservations SET status='open', updated_at=CURRENT_TIMESTAMP WHERE id=$1", reservation_id)
                updated = dict(row); updated["status"] = "open"; updated["participant_count"] = count
                return _reservation(updated)

    async def cancel(self, reservation_id: int, host_token_hash: str, now: datetime) -> None:
        result = await self._db.execute("""UPDATE reservations SET status='cancelled', cancelled_at=$1, updated_at=$1
            WHERE id=$2 AND host_token_hash=$3 AND status IN ('open','matched') AND start_at>$1""", now, reservation_id, host_token_hash)
        if result.endswith(" 0"):
            if await self._db.fetchval("SELECT 1 FROM reservations WHERE id=$1", reservation_id) is None: raise ReservationNotFoundError("Reservation not found")
            raise ReservationAccessError("Reservation cannot be cancelled with this credential")
