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
    # {character id: [wins, losses]}
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
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class MatchResultRow(Base):
    """One player's side of a match. Both sides seen means `counterpart_id` joins them."""

    __tablename__ = "match_results"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_match_results_event"),
        Index("idx_match_results_player", "npid", text("played_at DESC")),
        Index("idx_match_results_opponent", "opponent_npid"),
        Index("idx_match_results_room", "room_snapshot_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("match_events.id"), nullable=False)
    npid: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    chars: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opponent_npid: Mapped[str | None] = mapped_column(Text)
    room_snapshot_id: Mapped[int | None] = mapped_column(BigInteger)
    counterpart_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("match_results.id"))
