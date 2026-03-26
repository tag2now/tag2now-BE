"""PostgreSQL adapter for the history module using SQLAlchemy ORM."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from history.entities import HourlyStatsRow, RoomSnapshotRow, SnapshotMemberRow
from history.models import DailySummary, HourlyActivity, PlayerStats, RoomSnapshotRecord
from history.ports import HistoryPort

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
_HOURLY_RETENTION_DAYS = 90


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kst_hour_key() -> str:
	return datetime.now(KST).strftime("%Y-%m-%dT%H")


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class PostgresHistoryAdapter(HistoryPort):

	def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
		self._session_factory = session_factory

	async def init(self) -> None:
		logger.info("History adapter initialized (tables managed by shared database)")

	async def close(self) -> None:
		logger.info("History adapter closed")

	# -- Write ---------------------------------------------------------------

	async def record_snapshot(self, rooms: list[RoomSnapshotRecord]) -> None:
		if not rooms:
			return

		total_players = sum(r.current_members for r in rooms)
		total_rooms = len(rooms)

		async with self._session_factory() as session:
			async with session.begin():
				for room in rooms:
					snapshot = RoomSnapshotRow(
						room_id=room.room_id,
						room_type=room.room_type,
						owner_npid=room.owner_npid,
						owner_online_name=room.owner_online_name,
						current_members=room.current_members,
						max_slots=room.max_slots,
						is_matchmaking=room.is_matchmaking,
					)
					for npid, name in zip(room.member_npids, room.member_online_names):
						snapshot.members.append(SnapshotMemberRow(npid=npid, online_name=name))
					session.add(snapshot)

				# Upsert hourly stats
				hour_key = _kst_hour_key()
				stmt = pg_insert(HourlyStatsRow).values(
					hour_key=hour_key,
					total_players=total_players,
					total_rooms=total_rooms,
				)
				stmt = stmt.on_conflict_do_update(
					index_elements=["hour_key"],
					set_={
						"total_players": func.greatest(HourlyStatsRow.total_players, stmt.excluded.total_players),
						"total_rooms": func.greatest(HourlyStatsRow.total_rooms, stmt.excluded.total_rooms),
					},
				)
				await session.execute(stmt)

				# Cleanup old hourly aggregates (raw snapshots are kept indefinitely)
				await session.execute(
					delete(HourlyStatsRow).where(
						HourlyStatsRow.captured_at < func.now() - timedelta(days=_HOURLY_RETENTION_DAYS)
					)
				)

	# -- Read: global stats --------------------------------------------------

	async def get_hourly_activity(self, days: int = 7) -> list[HourlyActivity]:
		start_key = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%dT%H")

		stmt = (
			select(
				func.cast(func.split_part(HourlyStatsRow.hour_key, "T", 2), Integer).label("hour"),
				func.round(func.avg(HourlyStatsRow.total_players), 1).label("avg_players"),
				func.max(HourlyStatsRow.total_players).label("peak_players"),
			)
			.where(HourlyStatsRow.hour_key >= start_key)
			.group_by("hour")
			.order_by("hour")
		)

		async with self._session_factory() as session:
			result = await session.execute(stmt)
			result_map = {
				row.hour: HourlyActivity(hour=row.hour, avg_players=float(row.avg_players), peak_players=row.peak_players)
				for row in result
			}

		return [
			result_map.get(h, HourlyActivity(hour=h, avg_players=0, peak_players=0))
			for h in range(24)
		]

	async def get_daily_summary(self, days: int = 30) -> list[DailySummary]:
		stmt = (
			select(
				func.split_part(HourlyStatsRow.hour_key, "T", 1).label("date"),
				func.max(HourlyStatsRow.total_players).label("peak_players"),
				func.round(func.avg(HourlyStatsRow.total_players), 1).label("avg_players"),
				func.max(HourlyStatsRow.total_rooms).label("peak_rooms"),
			)
			.where(HourlyStatsRow.captured_at >= func.now() - timedelta(days=days))
			.group_by("date")
			.order_by(text("date DESC"))
		)

		async with self._session_factory() as session:
			result = await session.execute(stmt)
			return [
				DailySummary(date=row.date, peak_players=row.peak_players, avg_players=float(row.avg_players), peak_rooms=row.peak_rooms)
				for row in result
			]

	# -- Read: per-player stats ----------------------------------------------

	async def get_player_stats(self, npid: str, days: int = 30) -> PlayerStats:
		cutoff = func.now() - timedelta(days=days)

		# Build a subquery to find all snapshot IDs where the player appears
		player_snapshots = (
			select(RoomSnapshotRow.id, RoomSnapshotRow.captured_at, RoomSnapshotRow.room_type)
			.outerjoin(SnapshotMemberRow, SnapshotMemberRow.snapshot_id == RoomSnapshotRow.id)
			.where(
				or_(RoomSnapshotRow.owner_npid == npid, SnapshotMemberRow.npid == npid),
				RoomSnapshotRow.captured_at >= cutoff,
			)
			.subquery()
		)

		stats_stmt = select(
			func.count(func.distinct(func.cast(player_snapshots.c.captured_at, DateTime))).label("days_active"),
			func.count().label("times_seen"),
			func.min(player_snapshots.c.captured_at).label("first_seen"),
			func.max(player_snapshots.c.captured_at).label("last_seen"),
		)

		type_stmt = (
			select(
				player_snapshots.c.room_type,
				func.count().label("cnt"),
			)
			.group_by(player_snapshots.c.room_type)
		)

		async with self._session_factory() as session:
			row = (await session.execute(stats_stmt)).one_or_none()
			type_rows = (await session.execute(type_stmt)).all()

		return PlayerStats(
			npid=npid,
			days_active=row.days_active if row else 0,
			times_seen=row.times_seen if row else 0,
			first_seen=row.first_seen.isoformat() if row and row.first_seen else None,
			last_seen=row.last_seen.isoformat() if row and row.last_seen else None,
			room_type_counts={r.room_type: r.cnt for r in type_rows},
		)

	async def get_player_hours(self, npid: str, days: int = 7) -> list[int]:
		cutoff = func.now() - timedelta(days=days)

		stmt = (
			select(
				func.extract("hour", func.timezone("Asia/Seoul", RoomSnapshotRow.captured_at)).cast(Integer).label("hour"),
				func.count(func.distinct(func.cast(func.timezone("Asia/Seoul", RoomSnapshotRow.captured_at), DateTime))).label("day_count"),
			)
			.outerjoin(SnapshotMemberRow, SnapshotMemberRow.snapshot_id == RoomSnapshotRow.id)
			.where(
				or_(RoomSnapshotRow.owner_npid == npid, SnapshotMemberRow.npid == npid),
				RoomSnapshotRow.captured_at >= cutoff,
			)
			.group_by("hour")
		)

		async with self._session_factory() as session:
			result = await session.execute(stmt)
			return sorted(row.hour for row in result if row.day_count >= 2)
