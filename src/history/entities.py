"""SQLAlchemy ORM entities for the history module."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class RankMatchSnapshotRow(Base):
	__tablename__ = "rank_match_snapshots"

	# RPCN room ids come from an in-memory counter that restarts at 1 with the
	# server, so they are unique only within one RPCN uptime --- never the key.
	__table_args__ = (
		UniqueConstraint("room_id", "user1_npid", "user2_npid", "match_date",
						 name="uq_rank_match_snapshots_match"),
	)

	id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	room_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
	match_date: Mapped[date] = mapped_column(Date, nullable=False)
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


class DailyMatchedPlayerRow(Base):
	"""A player observed in a completed rank match on a KST calendar day."""
	__tablename__ = "daily_matched_players"

	date: Mapped[date] = mapped_column(Date, primary_key=True)
	npid: Mapped[str] = mapped_column(String, primary_key=True)
	first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActivitySnapshotRow(Base):
	__tablename__ = "activity_snapshots"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
	total_players: Mapped[int] = mapped_column(Integer, nullable=False)
	total_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
	rank_players: Mapped[int] = mapped_column(Integer, nullable=False)
	rank_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
