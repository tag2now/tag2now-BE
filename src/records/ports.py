"""Port interface for match records."""

from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from history.models import RankOpponent
from records.models import FinishedMatch, MatchEvent, MatchOutcome, PlayerSave


class RecordsPort(ABC):
    """Outbound port for compared saves, the event queue and match results."""

    # -- Capture -------------------------------------------------------------

    @abstractmethod
    async def latest_data_id(self, session: AsyncSession) -> int:
        """Return the newest data_id compared so far, 0 before any."""

    @abstractmethod
    async def lock_state(self, session: AsyncSession, npid: str) -> PlayerSave | None:
        """Return the player's last compared save, locked until the transaction ends."""

    @abstractmethod
    async def save_state(self, session: AsyncSession, save: PlayerSave, merged: bool) -> None:
        """Replace the player's last compared save, counting a merged change."""

    @abstractmethod
    async def add_event(self, session: AsyncSession, save: PlayerSave, match: FinishedMatch, now: datetime) -> None:
        """Queue the match this save finished."""

    # -- Queue ---------------------------------------------------------------

    @abstractmethod
    async def claim_event(self, session: AsyncSession, now: datetime) -> MatchEvent | None:
        """Return the oldest due event, locked until the transaction ends, skipping any already locked."""

    @abstractmethod
    async def finish_event(self, session: AsyncSession, event_id: int) -> None:
        """Mark the event handled."""

    @abstractmethod
    async def fail_event(self, session: AsyncSession, event: MatchEvent, error: str, now: datetime) -> None:
        """Schedule the event's next attempt, or bury it after the last."""

    # -- Results -------------------------------------------------------------

    @abstractmethod
    async def add_result(self, session: AsyncSession, event: MatchEvent, opponent: RankOpponent | None) -> int:
        """Store one player's side of a match and return its id."""

    @abstractmethod
    async def lock_room(self, session: AsyncSession, room_snapshot_id: int) -> None:
        """Serialize result writes for one room until the transaction ends."""

    @abstractmethod
    async def link_counterpart(
        self,
        session: AsyncSession,
        result_id: int,
        opponent: RankOpponent,
        wanted: MatchOutcome,
        played_at: datetime,
    ) -> bool:
        """Join a result to the opponent's side of the same match, when it has arrived."""
