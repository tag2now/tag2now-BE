"""PostgreSQL adapter for match records."""

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from history.entities import RankMatchSnapshotRow
from history.models import RankOpponent
from records.domain import seat
from records.entities import MatchEventRow, MatchResultRow, SaveStateRow
from records.models import (
    CharRecord,
    EventStatus,
    FinishedMatch,
    MatchEvent,
    MatchOutcome,
    MatchSide,
    PlayerSave,
    RecordedMatch,
)
from records.ports import RecordsPort

_MAX_ATTEMPTS = 5
_RETRY_DELAY = timedelta(seconds=30)
# Both sides save as the match ends, and the room's next match is further off than this.
_SAME_MATCH_WINDOW = timedelta(seconds=60)


def _to_save(row: SaveStateRow) -> PlayerSave:
    return PlayerSave(
        npid=row.npid,
        data_id=row.data_id,
        saved_at=row.saved_at,
        wins=row.wins,
        losses=row.losses,
        chars={int(char_id): CharRecord(*record) for char_id, record in row.chars.items()},
        own_chars=tuple(row.start_chars),
    )


def _optional_tuple(values: list | None) -> tuple | None:
    return None if values is None else tuple(values)


def _optional_list(values: tuple | None) -> list | None:
    """psycopg sends a tuple as a record, so an array column needs a list."""
    return None if values is None else list(values)


def _to_event(row: MatchEventRow) -> MatchEvent:
    return MatchEvent(
        id=row.id,
        npid=row.npid,
        result=MatchOutcome(row.result),
        chars=tuple(row.chars),
        saved_at=row.saved_at,
        ranks=_optional_tuple(row.ranks),
        attempts=row.attempts,
    )


def _room_name(room: RankMatchSnapshotRow | None, npid: str) -> str | None:
    if room is None:
        return None
    return {room.user1_npid: room.user1_online_name, room.user2_npid: room.user2_online_name}.get(npid)


def _side(row: MatchResultRow, room: RankMatchSnapshotRow | None) -> MatchSide:
    return MatchSide(
        row.npid, _room_name(room, row.npid), MatchOutcome(row.result), tuple(row.chars), _optional_tuple(row.ranks)
    )


def _opponent_side(
    shown: MatchResultRow, counterpart: MatchResultRow | None, room: RankMatchSnapshotRow | None
) -> MatchSide | None:
    """The other player: their own row when their save was seen, else only who the room says they were."""
    if counterpart is not None:
        return _side(counterpart, room)
    if shown.opponent_npid is None:
        return None
    result = MatchOutcome(shown.result).opposite
    return MatchSide(shown.opponent_npid, _room_name(room, shown.opponent_npid), result, None, None)


def _to_match(
    shown: MatchResultRow, counterpart: MatchResultRow | None, room: RankMatchSnapshotRow | None
) -> RecordedMatch:
    own, other = _side(shown, room), _opponent_side(shown, counterpart, room)
    p1, p2 = seat(own, other, room.user1_npid if room else None)
    return RecordedMatch(id=shown.id, played_at=shown.played_at, p1=p1, p2=p2)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PostgresRecordsAdapter(RecordsPort):
    # -- Capture -------------------------------------------------------------

    async def latest_data_id(self, session: AsyncSession) -> int:
        return (await session.execute(select(func.coalesce(func.max(SaveStateRow.data_id), 0)))).scalar_one()

    async def lock_state(self, session: AsyncSession, npid: str) -> PlayerSave | None:
        row = (
            await session.execute(select(SaveStateRow).where(SaveStateRow.npid == npid).with_for_update())
        ).scalar_one_or_none()
        return None if row is None else _to_save(row)

    async def save_state(self, session: AsyncSession, save: PlayerSave, merged: bool) -> None:
        values = dict(
            data_id=save.data_id,
            saved_at=save.saved_at,
            wins=save.wins,
            losses=save.losses,
            chars={char_id: list(record) for char_id, record in save.chars.items()},
            start_chars=list(save.own_chars),
        )
        stmt = pg_insert(SaveStateRow).values(npid=save.npid, **values)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["npid"],
                set_={**values, "merged_count": SaveStateRow.merged_count + int(merged)},
            )
        )

    async def add_event(self, session: AsyncSession, save: PlayerSave, match: FinishedMatch, now: datetime) -> None:
        await session.execute(
            pg_insert(MatchEventRow)
            .values(
                npid=save.npid,
                data_id=save.data_id,
                result=match.result,
                chars=list(match.chars),
                ranks=list(match.ranks),
                saved_at=save.saved_at,
                available_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_match_events_save")
        )

    # -- Queue ---------------------------------------------------------------

    async def claim_event(self, session: AsyncSession, now: datetime) -> MatchEvent | None:
        row = (
            await session.execute(
                select(MatchEventRow)
                .where(MatchEventRow.status == EventStatus.PENDING, MatchEventRow.available_at <= now)
                .order_by(MatchEventRow.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        return None if row is None else _to_event(row)

    async def finish_event(self, session: AsyncSession, event_id: int) -> None:
        await session.execute(
            update(MatchEventRow).where(MatchEventRow.id == event_id).values(status=EventStatus.DONE, last_error=None)
        )

    async def fail_event(self, session: AsyncSession, event: MatchEvent, error: str, now: datetime) -> None:
        attempts = event.attempts + 1
        await session.execute(
            update(MatchEventRow)
            .where(MatchEventRow.id == event.id)
            .values(
                attempts=attempts,
                last_error=error,
                available_at=now + _RETRY_DELAY * attempts,
                status=EventStatus.DEAD if attempts >= _MAX_ATTEMPTS else EventStatus.PENDING,
            )
        )

    # -- Results -------------------------------------------------------------

    async def add_result(self, session: AsyncSession, event: MatchEvent, opponent: RankOpponent | None) -> int:
        result = MatchResultRow(
            event_id=event.id,
            npid=event.npid,
            result=event.result,
            chars=list(event.chars),
            ranks=_optional_list(event.ranks),
            played_at=event.saved_at,
            opponent_npid=opponent.npid if opponent else None,
            room_snapshot_id=opponent.room_snapshot_id if opponent else None,
        )
        session.add(result)
        await session.flush()
        return result.id

    async def lock_room(self, session: AsyncSession, room_snapshot_id: int) -> None:
        await session.execute(select(func.pg_advisory_xact_lock(room_snapshot_id)))

    async def link_counterpart(
        self,
        session: AsyncSession,
        result_id: int,
        opponent: RankOpponent,
        wanted: MatchOutcome,
        played_at: datetime,
    ) -> bool:
        distance = func.abs(func.extract("epoch", MatchResultRow.played_at - played_at))
        counterpart_id = (
            await session.execute(
                select(MatchResultRow.id)
                .where(
                    MatchResultRow.room_snapshot_id == opponent.room_snapshot_id,
                    MatchResultRow.npid == opponent.npid,
                    MatchResultRow.result == wanted,
                    MatchResultRow.counterpart_id.is_(None),
                    MatchResultRow.played_at.between(played_at - _SAME_MATCH_WINDOW, played_at + _SAME_MATCH_WINDOW),
                )
                .order_by(distance)
                .limit(1)
            )
        ).scalar_one_or_none()
        if counterpart_id is None:
            return False
        await session.execute(
            update(MatchResultRow).where(MatchResultRow.id == result_id).values(counterpart_id=counterpart_id)
        )
        await session.execute(
            update(MatchResultRow).where(MatchResultRow.id == counterpart_id).values(counterpart_id=result_id)
        )
        return True

    # -- Reading -------------------------------------------------------------

    async def list_matches(
        self, session: AsyncSession, npid: str | None, query: str | None, before: int | None, limit: int
    ) -> list[RecordedMatch]:
        shown, counterpart, room = MatchResultRow, aliased(MatchResultRow), RankMatchSnapshotRow
        # A match whose both sides were seen is two rows; the lower id stands for it.
        conditions = [or_(shown.counterpart_id.is_(None), shown.id < shown.counterpart_id)]
        if before is not None:
            conditions.append(shown.id < before)
        if npid is not None:
            conditions.append(or_(shown.npid == npid, shown.opponent_npid == npid))
        if query:
            pattern = f"%{_escape_like(query)}%"
            names = (shown.npid, shown.opponent_npid, room.user1_online_name, room.user2_online_name)
            conditions.append(or_(*(name.ilike(pattern, escape="\\") for name in names)))
        rows = await session.execute(
            select(shown, counterpart, room)
            .outerjoin(counterpart, counterpart.id == shown.counterpart_id)
            .outerjoin(room, room.id == shown.room_snapshot_id)
            .where(*conditions)
            .order_by(shown.id.desc())
            .limit(limit)
        )
        return [_to_match(*row) for row in rows]
