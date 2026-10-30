"""Independent, in-process collection of room activity, ranked participants and rank matches."""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from history.models import ActivitySnapshot, RankMatchSnapshotRecord
from history.service import HistoryService
from matching.models import RoomInfoDTO
from matching.service import MatchingService
from shared.settings import get_settings
from shared.ttt2 import TTT2_COM_ID

logger = logging.getLogger(__name__)


def _to_snapshot_record(room: RoomInfoDTO, observed_at: datetime) -> RankMatchSnapshotRecord:
    u1 = room.users[0] if len(room.users) > 0 else None
    u2 = room.users[1] if len(room.users) > 1 else None
    return RankMatchSnapshotRecord(
        room_id=room.room_id,
        rank_id=room.rank_info.id,
        user1_npid=u1.npid if u1 else "",
        user1_online_name=u1.online_name if u1 else "",
        user2_npid=u2.npid if u2 else "",
        user2_online_name=u2.online_name if u2 else "",
        created_dt=observed_at,
    )


class Collector:
    def __init__(self, matching: MatchingService, history: HistoryService):
        self._matching = matching
        self._history = history
        # Room ids of the matches in progress at the last recorded cycle, so a match is
        # written once, on the cycle it first appears. A restart empties this set; the
        # unique key on rank_match_snapshots catches the matches it then sees again.
        self._prev_rank_match_ids: set[int] = set()

    async def _record_new_rank_matches(self, rooms: list[RoomInfoDTO], observed_at: datetime) -> None:
        """Record matches absent from the previous cycle.

        The previous set advances only after the write commits, so a failed write
        is retried on the next cycle instead of being lost.
        """
        new_rooms = [room for room in rooms if room.room_id not in self._prev_rank_match_ids]
        if new_rooms:
            await self._history.record_snapshot([_to_snapshot_record(room, observed_at) for room in new_rooms])
        self._prev_rank_match_ids = {room.room_id for room in rooms}

    async def collect_once(self) -> None:
        """Store the current activity snapshot, ranked-room participants and new rank matches."""
        observed_at = datetime.now(timezone.utc)
        observation = await self._matching.collect_activity_observation(TTT2_COM_ID)
        await self._history.record_daily_matched_players(observation.rank_player_npids, observed_at)
        await self._history.record_activity_snapshot(
            ActivitySnapshot(
                observed_at=observed_at,
                total_players=observation.total_players,
                total_rooms=observation.total_rooms,
                rank_players=observation.rank_players,
                rank_rooms=observation.rank_rooms,
            )
        )
        await self._record_new_rank_matches(observation.rank_matches, observed_at)

    async def run(self) -> None:
        """Run immediately, then at the configured interval until cancelled."""
        interval = get_settings().match_history_collection_interval_seconds
        while True:
            try:
                await self.collect_once()
            except Exception:
                logger.warning("Match-history collection failed", exc_info=True)
            await asyncio.sleep(interval)


async def stop_collector(task: asyncio.Task[None]) -> None:
    """Cancel the background task before database dependencies are closed."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
