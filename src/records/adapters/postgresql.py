"""PostgreSQL adapter for match records."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, case, func, not_, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from history.entities import RankMatchSnapshotRow
from history.models import RankRoom
from records.domain import outcome_of
from records.entities import MatchEventRow, MatchRow, SaveStateRow
from records.models import (
    CharTally,
    EventStatus,
    MatchEvent,
    MatchOutcome,
    MatchPlayer,
    OpponentRecord,
    PlayerMatch,
    PlayerSave,
    RecordedMatch,
    Side,
    WeeklyPlayer,
)
from records.ports import RecordsPort

_MAX_ATTEMPTS = 5
_RETRY_DELAY = timedelta(seconds=30)
# Both players save as the match ends, and the room's next match is further off than this.
_SAME_MATCH_WINDOW = timedelta(seconds=60)
_EVENT_IDS = {Side.P1: MatchRow.p1_event_id, Side.P2: MatchRow.p2_event_id}


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


def _player(
    npid: str, side: Side, match: MatchRow, event: MatchEventRow | None, room: RankMatchSnapshotRow | None
) -> MatchPlayer:
    online_name = None if room is None else room.online_name_of(npid)
    outcome = outcome_of(side, Side(match.winner))
    if event is None:
        return MatchPlayer(npid, online_name, outcome, None, None)
    return MatchPlayer(npid, online_name, outcome, tuple(event.chars), _optional_tuple(event.ranks))


def _recorded_match(
    match: MatchRow,
    room: RankMatchSnapshotRow | None,
    p1_event: MatchEventRow | None,
    p2_event: MatchEventRow | None,
) -> RecordedMatch:
    p1 = _player(match.p1_npid, Side.P1, match, p1_event, room)
    p2 = None if match.p2_npid is None else _player(match.p2_npid, Side.P2, match, p2_event, room)
    return RecordedMatch(id=match.id, played_at=match.played_at, p1=p1, p2=p2)


def _players():
    """Every match once per player: against whom, whether they won, and whether their own save was seen."""

    def one(side: Side, npid, opponent_npid):
        return select(
            MatchRow.played_at,
            MatchRow.room_snapshot_id,
            npid.label("npid"),
            opponent_npid.label("opponent_npid"),
            (MatchRow.winner == side).label("won"),
            _EVENT_IDS[side].is_not(None).label("seen"),
        )

    return union_all(
        one(Side.P1, MatchRow.p1_npid, MatchRow.p2_npid), one(Side.P2, MatchRow.p2_npid, MatchRow.p1_npid)
    ).subquery("players")


def _counted(players):
    """What both player tallies count: matches the player's own save showed, against an opponent a room named."""
    return and_(players.c.seen, players.c.opponent_npid.is_not(None))


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

    # -- Matches -------------------------------------------------------------

    async def lock_room(self, session: AsyncSession, room_snapshot_id: int) -> None:
        await session.execute(select(func.pg_advisory_xact_lock(room_snapshot_id)))

    async def fill_side(
        self, session: AsyncSession, event: MatchEvent, room: RankRoom, side: Side, winner: Side
    ) -> bool:
        event_id = _EVENT_IDS[side]
        distance = func.abs(func.extract("epoch", MatchRow.played_at - event.saved_at))
        window = (event.saved_at - _SAME_MATCH_WINDOW, event.saved_at + _SAME_MATCH_WINDOW)
        match_id = (
            await session.execute(
                select(MatchRow.id)
                .where(
                    MatchRow.room_snapshot_id == room.room_snapshot_id,
                    MatchRow.winner == winner,
                    event_id.is_(None),
                    MatchRow.played_at.between(*window),
                )
                .order_by(distance)
                .limit(1)
            )
        ).scalar_one_or_none()
        if match_id is None:
            return False
        await session.execute(update(MatchRow).where(MatchRow.id == match_id).values({event_id: event.id}))
        return True

    async def add_match(
        self, session: AsyncSession, event: MatchEvent, room: RankRoom | None, side: Side, winner: Side
    ) -> None:
        p1_npid, p2_npid = (event.npid, None) if room is None else (room.user1_npid, room.user2_npid)
        session.add(
            MatchRow(
                played_at=event.saved_at,
                room_snapshot_id=None if room is None else room.room_snapshot_id,
                p1_npid=p1_npid,
                p2_npid=p2_npid,
                winner=winner,
                **{_EVENT_IDS[side].key: event.id},
            )
        )
        await session.flush()

    # -- Reading -------------------------------------------------------------

    async def list_matches(
        self, session: AsyncSession, npid: str | None, name_query: str | None, before: int | None, limit: int
    ) -> list[RecordedMatch]:
        match, room = MatchRow, RankMatchSnapshotRow
        p1_event, p2_event = aliased(MatchEventRow), aliased(MatchEventRow)
        conditions = []
        if before is not None:
            conditions.append(match.id < before)
        if npid is not None:
            conditions.append(or_(match.p1_npid == npid, match.p2_npid == npid))
        if name_query:
            pattern = f"%{_escape_like(name_query)}%"
            names = (match.p1_npid, match.p2_npid, room.user1_online_name, room.user2_online_name)
            conditions.append(or_(*(name.ilike(pattern, escape="\\") for name in names)))
        rows = await session.execute(
            select(match, room, p1_event, p2_event)
            .outerjoin(room, room.id == match.room_snapshot_id)
            .outerjoin(p1_event, p1_event.id == match.p1_event_id)
            .outerjoin(p2_event, p2_event.id == match.p2_event_id)
            .where(*conditions)
            .order_by(match.id.desc())
            .limit(limit)
        )
        return [_recorded_match(*row) for row in rows]

    async def weekly_top_players(
        self, session: AsyncSession, since: datetime, limit: int, excluded_npids: Sequence[str]
    ) -> list[WeeklyPlayer]:
        players, room = _players(), RankMatchSnapshotRow
        # RPCN usernames are unique case-insensitively, so the list is too.
        excluded = [npid.lower() for npid in excluded_npids]
        online_name = case((room.user1_npid == players.c.npid, room.user1_online_name), else_=room.user2_online_name)
        match_count = func.count()
        rows = await session.execute(
            select(
                players.c.npid,
                func.max(online_name).label("online_name"),
                match_count.label("match_count"),
                func.count().filter(players.c.won).label("wins"),
                func.count().filter(not_(players.c.won)).label("losses"),
            )
            # A match with an opponent always has its room.
            .join(room, room.id == players.c.room_snapshot_id)
            .where(_counted(players), players.c.played_at >= since, func.lower(players.c.npid).not_in(excluded))
            .group_by(players.c.npid)
            .order_by(match_count.desc(), players.c.npid)
            .limit(limit)
        )
        return [WeeklyPlayer(row.npid, row.online_name, row.match_count, row.wins, row.losses) for row in rows]

    async def frequent_opponents(
        self, session: AsyncSession, npid: str, since: datetime, limit: int
    ) -> list[OpponentRecord]:
        players, room = _players(), RankMatchSnapshotRow
        online_name = case(
            (room.user1_npid == players.c.opponent_npid, room.user1_online_name), else_=room.user2_online_name
        )
        match_count = func.count()
        rows = await session.execute(
            select(
                players.c.opponent_npid,
                func.max(online_name).label("online_name"),
                match_count.label("match_count"),
                func.count().filter(players.c.won).label("wins"),
                func.count().filter(not_(players.c.won)).label("losses"),
            )
            # A match with an opponent always has its room.
            .join(room, room.id == players.c.room_snapshot_id)
            .where(_counted(players), players.c.npid == npid, players.c.played_at >= since)
            .group_by(players.c.opponent_npid)
            .order_by(match_count.desc(), players.c.opponent_npid)
            .limit(limit)
        )
        return [
            OpponentRecord(row.opponent_npid, row.online_name, row.match_count, row.wins, row.losses) for row in rows
        ]
