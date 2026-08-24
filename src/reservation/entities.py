"""SQLAlchemy ORM entities for reservation persistence."""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Identity, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from shared.database import Base

class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    __table_args__ = (Index("idx_reservations_start_at", "start_at"),)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    host_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    host_subject: Mapped[str | None] = mapped_column(Text)
    host_ranks: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    host_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    memo: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ReservationParticipant(Base):
    __tablename__ = "reservation_participants"
    __table_args__ = (
        UniqueConstraint("reservation_id", "participant_token_hash"),
        Index("idx_reservation_participants_active", "reservation_id", postgresql_where="cancelled_at IS NULL"),
    )
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    ranks: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    participant_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
