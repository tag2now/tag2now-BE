"""SQLAlchemy ORM entities for match records."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class SaveStateRow(Base):
    """The last save compared for a player: one row each, replaced by the next."""

    __tablename__ = "save_states"

    npid: Mapped[str] = mapped_column(Text, primary_key=True)
    data_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wins: Mapped[int] = mapped_column(Integer, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, nullable=False)
    # {character id: [wins, losses, rank]}; states kept before ranks have two.
    chars: Mapped[dict] = mapped_column(JSONB, nullable=False)
    start_chars: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    merged_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class MatchEventRow(Base):
    """A finished match as one player's save showed it, and the queue of those not yet resolved."""

    __tablename__ = "match_events"
    __table_args__ = (
        UniqueConstraint("npid", "data_id", name="uq_match_events_save"),
        CheckConstraint("result IN ('win', 'loss')", name="match_events_result_check"),
        CheckConstraint("status IN ('pending', 'done', 'dead')", name="match_events_status_check"),
        Index("idx_match_events_pending", "id", postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    npid: Mapped[str] = mapped_column(Text, nullable=False)
    data_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    chars: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    # Rank going in, per character of `chars`; null on events queued before ranks were kept.
    ranks: Mapped[list[int | None] | None] = mapped_column(ARRAY(Integer))
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class MatchRow(Base):
    """One match: who played on which side, which side won, and each side's event once its save is seen."""

    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("p1_event_id", name="uq_matches_p1_event"),
        UniqueConstraint("p2_event_id", name="uq_matches_p2_event"),
        CheckConstraint("winner IN (1, 2)", name="matches_winner_check"),
        CheckConstraint("p1_event_id IS NOT NULL OR p2_event_id IS NOT NULL", name="matches_seen_check"),
        CheckConstraint("(room_snapshot_id IS NULL) = (p2_npid IS NULL)", name="matches_room_check"),
        Index("idx_matches_p1", "p1_npid", text("id DESC")),
        Index("idx_matches_p2", "p2_npid", text("id DESC")),
        Index("idx_matches_room", "room_snapshot_id"),
        Index("idx_matches_played_at", "played_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # The first event's save; the other side's lands within a minute of it.
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    room_snapshot_id: Mapped[int | None] = mapped_column(BigInteger)
    p1_npid: Mapped[str] = mapped_column(Text, nullable=False)
    # None only when no room named the opponent.
    p2_npid: Mapped[str | None] = mapped_column(Text)
    winner: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    p1_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("match_events.id"))
    p2_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("match_events.id"))
