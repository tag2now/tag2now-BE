"""Port interface for match records."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from history.models import RankRoom
from records.models import (
    MatchEvent,
    OpponentRecord,
    PlayerMatch,
    PlayerSave,
    RecordedMatch,
    Side,
    WeeklyPlayer,
)


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
    async def add_event(self, session: AsyncSession, save: PlayerSave, match: PlayerMatch, now: datetime) -> None:
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

    # -- Matches -------------------------------------------------------------

    @abstractmethod
    async def lock_room(self, session: AsyncSession, room_snapshot_id: int) -> None:
        """Serialize match writes for one room until the transaction ends."""

    @abstractmethod
    async def fill_side(
        self, session: AsyncSession, event: MatchEvent, room: RankRoom, side: Side, winner: Side
    ) -> bool:
        """Put the event on a match of that room, near its save, with the same winner and `side` still unseen.
        False when there is none."""

    @abstractmethod
    async def add_match(
        self, session: AsyncSession, event: MatchEvent, room: RankRoom | None, side: Side, winner: Side
    ) -> None:
        """Record a new match with the event on `side`."""

    # -- Reading -------------------------------------------------------------

    @abstractmethod
    async def list_matches(
        self, session: AsyncSession, npid: str | None, name_query: str | None, before: int | None, limit: int
    ) -> list[RecordedMatch]:
        """Return up to `limit` matches older than `before`, newest first: one each, whoever was seen.
        `npid` keeps that player's; `name_query` those with a player whose id or name contains it."""

    @abstractmethod
    async def weekly_top_players(
        self, session: AsyncSession, since: datetime, limit: int, excluded_npids: Sequence[str]
    ) -> list[WeeklyPlayer]:
        """Return the `limit` players with the most matches since `since`, counting only matches
        their own save showed against a known opponent, and skipping excluded npids."""

    @abstractmethod
    async def frequent_opponents(
        self, session: AsyncSession, npid: str, since: datetime, limit: int
    ) -> list[OpponentRecord]:
        """Return the `limit` opponents the player met most since `since`, counting only matches
        the player's own save showed."""
