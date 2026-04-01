"""SQLAlchemy ORM entities for the history module."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database import Base


class RoomSnapshotRow(Base):
	__tablename__ = "room_snapshots"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
	room_id: Mapped[int] = mapped_column(Integer, nullable=False)
	room_type: Mapped[str] = mapped_column(String, nullable=False)
	owner_npid: Mapped[str] = mapped_column(String, nullable=False)
	owner_online_name: Mapped[str] = mapped_column(String, nullable=False)
	current_members: Mapped[int] = mapped_column(Integer, nullable=False)
	max_slots: Mapped[int] = mapped_column(Integer, nullable=False)
	is_matchmaking: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

	members: Mapped[list["SnapshotMemberRow"]] = relationship(
		back_populates="snapshot", cascade="all, delete-orphan",
	)


class SnapshotMemberRow(Base):
	__tablename__ = "room_snapshot_members"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	snapshot_id: Mapped[int] = mapped_column(ForeignKey("room_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
	npid: Mapped[str] = mapped_column(String, nullable=False, index=True)
	online_name: Mapped[str] = mapped_column(String, nullable=False, server_default="")

	snapshot: Mapped["RoomSnapshotRow"] = relationship(back_populates="members")


class HourlyStatsRow(Base):
	__tablename__ = "hourly_stats"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	hour_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
	total_players: Mapped[int] = mapped_column(Integer, nullable=False)
	total_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
	captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
