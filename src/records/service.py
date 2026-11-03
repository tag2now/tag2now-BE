"""Match records: finished matches found in saves, then resolved to who played whom.

Comparing a save and queueing its match commit together, so a match is either
queued and compared or neither. Resolving one takes the room it was played in.
"""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from history.service import HistoryService
from records import domain
from records.models import MatchEvent, MatchRecordOut, MatchRecordPageOut, PlayerSave
from records.ports import RecordsPort
from saves.ports import SaveServer
from shared.clock import Clock, SystemClock

logger = logging.getLogger(__name__)

_CAPTURE_LIMIT = 200
# data_ids are handed out before their row commits, so a lower id can appear after a higher one.
_CAPTURE_OVERLAP = 16


class RecordsService:
    def __init__(
        self,
        repo: RecordsPort,
        sessions: async_sessionmaker[AsyncSession],
        saves: SaveServer,
        history: HistoryService,
        clock: Clock | None = None,
    ):
        self._repo = repo
        self._sessions = sessions
        self._saves = saves
        self._history = history
        self._clock = clock or SystemClock()

    # -- Capture -------------------------------------------------------------

    async def capture(self) -> None:
        """Compare every save written since the last capture. One bad save holds up no other."""
        async with self._sessions() as session:
            latest = await self._repo.latest_data_id(session)
        for answer in await self._saves.read_changed(max(latest - _CAPTURE_OVERLAP, 0), _CAPTURE_LIMIT):
            try:
                await self._compare(PlayerSave.from_answer(answer))
            except Exception:
                logger.exception("Save %s could not be compared", answer.get("data_id"))

    async def _compare(self, save: PlayerSave) -> None:
        async with self._sessions() as session, session.begin():
            before = await self._repo.lock_state(session, save.npid)
            if before is None:
                await self._repo.save_state(session, save, merged=False)
                return
            if save.data_id <= before.data_id:
                return
            comparison = domain.compare(before, save)
            await self._repo.save_state(session, save, comparison.merged)
            if comparison.match is not None:
                await self._repo.add_event(session, save, comparison.match, self._clock.now())

    # -- Queue ---------------------------------------------------------------

    async def process_next(self) -> bool:
        """Resolve the oldest due event. False when none is due."""
        async with self._sessions() as session, session.begin():
            now = self._clock.now()
            event = await self._repo.claim_event(session, now)
            if event is None:
                return False
            await self._attempt(session, event, now)
        return True

    async def _attempt(self, session: AsyncSession, event: MatchEvent, now: datetime) -> None:
        """A failure rolls back to the savepoint, so the event stays locked while its
        retry is recorded in the same transaction."""
        try:
            async with session.begin_nested():
                await self._resolve(session, event)
                await self._repo.finish_event(session, event.id)
        except Exception as exc:
            logger.exception("Match event %s failed", event.id)
            await self._repo.fail_event(session, event, str(exc), now)

    async def _resolve(self, session: AsyncSession, event: MatchEvent) -> None:
        opponent = await self._history.rank_opponent(event.npid, event.saved_at)
        if opponent is None:
            await self._repo.add_result(session, event, None)
            return
        await self._repo.lock_room(session, opponent.room_snapshot_id)
        result_id = await self._repo.add_result(session, event, opponent)
        await self._repo.link_counterpart(session, result_id, opponent, event.outcome.opposite, event.saved_at)

    # -- Reading -------------------------------------------------------------

    async def list_matches(
        self, npid: str | None, name_query: str | None, before: int | None, limit: int
    ) -> MatchRecordPageOut:
        """Paged by id rather than by page number, so matches recorded meanwhile do not shift the next page."""
        async with self._sessions() as session:
            found = await self._repo.list_matches(session, npid, name_query, before, limit + 1)
        next_before = found[limit - 1].id if len(found) > limit else None
        shown = found[:limit]
        return MatchRecordPageOut(matches=[MatchRecordOut.of(match) for match in shown], next_before=next_before)
