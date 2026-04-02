"""SQLAlchemy ORM entities for the history module."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class RankMatchSnapshotRow(Base):
	__tablename__ = "rank_match_snapshots"

	room_id: Mapped[int] = mapped_column(Integer, primary_key=True)
	created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
	rank_id: Mapped[int] = mapped_column(Integer, nullable=False)
	user1_npid: Mapped[str] = mapped_column(String, nullable=False, index=True)
	user1_online_name: Mapped[str] = mapped_column(String, nullable=False)
	user2_npid: Mapped[str] = mapped_column(String, nullable=False, index=True)
	user2_online_name: Mapped[str] = mapped_column(String, nullable=False)


class HourlyStatsRow(Base):
	__tablename__ = "hourly_stats"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	hour_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
	total_players: Mapped[int] = mapped_column(Integer, nullable=False)
	total_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
	captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
