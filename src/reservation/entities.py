"""SQLAlchemy ORM entities for reservation persistence."""

from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from shared.database import Base

class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    __table_args__ = (Index("idx_reservations_start_at", "start_at"),)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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

class ReservationComment(Base):
    __tablename__ = "reservation_comments"
    __table_args__ = (
        CheckConstraint("length(body) <= 500", name="reservation_comments_body_check"),
        Index("idx_reservation_comments_active", "reservation_id", postgresql_where="deleted_at IS NULL"),
    )
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
