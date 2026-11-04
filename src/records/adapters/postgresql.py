"""PostgreSQL adapter for match records."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from history.entities import RankMatchSnapshotRow
from history.models import RankOpponent
from records.domain import seat
from records.entities import MatchEventRow, MatchResultRow, SaveStateRow
from records.models import (
    CharTally,
    EventStatus,
    MatchEvent,
    MatchOutcome,
    MatchPlayer,
    PlayerMatch,
    PlayerSave,
    RecordedMatch,
    WeeklyPlayer,
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
        tallies={int(char_id): CharTally(*tally) for char_id, tally in row.chars.items()},
        entered_chars=tuple(row.start_chars),
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
        outcome=MatchOutcome(row.result),
        chars=tuple(row.chars),
        saved_at=row.saved_at,
        ranks=_optional_tuple(row.ranks),
        attempts=row.attempts,
    )


def _player_from_result_row(row: MatchResultRow, room: RankMatchSnapshotRow | None) -> MatchPlayer:
    online_name = None if room is None else room.online_name_of(row.npid)
    return MatchPlayer(row.npid, online_name, MatchOutcome(row.result), tuple(row.chars), _optional_tuple(row.ranks))


def _opponent_player(
    representative_row: MatchResultRow, opponent_row: MatchResultRow | None, room: RankMatchSnapshotRow | None
) -> MatchPlayer | None:
    """The other player: their own row when their save was seen, else only who the room says they were."""
    if opponent_row is not None:
        return _player_from_result_row(opponent_row, room)
    npid = representative_row.opponent_npid
    if npid is None:
        return None
    online_name = None if room is None else room.online_name_of(npid)
    return MatchPlayer(npid, online_name, MatchOutcome(representative_row.result).opposite, None, None)


def _match_from_rows(
    representative_row: MatchResultRow, opponent_row: MatchResultRow | None, room: RankMatchSnapshotRow | None
) -> RecordedMatch:
    seen = _player_from_result_row(representative_row, room)
    opponent = _opponent_player(representative_row, opponent_row, room)
    p1, p2 = seat(seen, opponent, None if room is None else room.user1_npid)
    return RecordedMatch(id=representative_row.id, played_at=representative_row.played_at, p1=p1, p2=p2)


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
            chars={char_id: list(tally) for char_id, tally in save.tallies.items()},
            start_chars=list(save.entered_chars),
        )
        stmt = pg_insert(SaveStateRow).values(npid=save.npid, **values)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["npid"],
                set_={**values, "merged_count": SaveStateRow.merged_count + int(merged)},
            )
        )

    async def add_event(self, session: AsyncSession, save: PlayerSave, match: PlayerMatch, now: datetime) -> None:
        await session.execute(
            pg_insert(MatchEventRow)
            .values(
                npid=save.npid,
                data_id=save.data_id,
                result=match.outcome,
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
            result=event.outcome,
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
        self, session: AsyncSession, npid: str | None, name_query: str | None, before: int | None, limit: int
    ) -> list[RecordedMatch]:
        representative_row, opponent_row, room = MatchResultRow, aliased(MatchResultRow), RankMatchSnapshotRow
        # A match whose both sides were seen is two rows; the lower id stands for it.
        conditions = [
            or_(representative_row.counterpart_id.is_(None), representative_row.id < representative_row.counterpart_id)
        ]
        if before is not None:
            conditions.append(representative_row.id < before)
        if npid is not None:
            conditions.append(or_(representative_row.npid == npid, representative_row.opponent_npid == npid))
        if name_query:
            pattern = f"%{_escape_like(name_query)}%"
            names = (
                representative_row.npid,
                representative_row.opponent_npid,
                room.user1_online_name,
                room.user2_online_name,
            )
            conditions.append(or_(*(name.ilike(pattern, escape="\\") for name in names)))
        rows = await session.execute(
            select(representative_row, opponent_row, room)
            .outerjoin(opponent_row, opponent_row.id == representative_row.counterpart_id)
            .outerjoin(room, room.id == representative_row.room_snapshot_id)
            .where(*conditions)
            .order_by(representative_row.id.desc())
            .limit(limit)
        )
        return [_match_from_rows(*row) for row in rows]

    async def weekly_top_players(
        self, session: AsyncSession, since: datetime, limit: int, excluded_npids: Sequence[str]
    ) -> list[WeeklyPlayer]:
        own, room = MatchResultRow, RankMatchSnapshotRow
        # RPCN usernames are unique case-insensitively, so the list is too.
        excluded = [npid.lower() for npid in excluded_npids]
        online_name = case((room.user1_npid == own.npid, room.user1_online_name), else_=room.user2_online_name)
        match_count = func.count()
        rows = await session.execute(
            select(
                own.npid,
                func.max(online_name).label("online_name"),
                match_count.label("match_count"),
                func.count().filter(own.result == MatchOutcome.WIN).label("wins"),
                func.count().filter(own.result == MatchOutcome.LOSS).label("losses"),
            )
            # A linked result always has its room.
            .join(room, room.id == own.room_snapshot_id)
            .where(
                own.counterpart_id.is_not(None),
                own.played_at >= since,
                func.lower(own.npid).not_in(excluded),
            )
            .group_by(own.npid)
            .order_by(match_count.desc(), own.npid)
            .limit(limit)
        )
        return [WeeklyPlayer(row.npid, row.online_name, row.match_count, row.wins, row.losses) for row in rows]
