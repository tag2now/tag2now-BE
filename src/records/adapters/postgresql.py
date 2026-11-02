"""PostgreSQL adapter for match records."""

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from history.models import RankOpponent
from records.entities import MatchEventRow, MatchResultRow, SaveStateRow
from records.models import CharRecord, EventStatus, FinishedMatch, MatchEvent, MatchOutcome, PlayerSave
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


def _to_event(row: MatchEventRow) -> MatchEvent:
    return MatchEvent(
        id=row.id,
        npid=row.npid,
        result=MatchOutcome(row.result),
        chars=tuple(row.chars),
        saved_at=row.saved_at,
        attempts=row.attempts,
    )


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
