"""PostgreSQL adapter for the history module using SQLAlchemy ORM."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, case, delete, func, or_, select, text, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from history.entities import HourlyStatsRow, RankMatchSnapshotRow
from history.models import CoPlayer, DailySummary, HourlyActivity, PlayerStats, RankMatchSnapshotRecord, TopPlayer
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

	# -- Write ---------------------------------------------------------------

	async def record_snapshot(self, session: AsyncSession, rooms: list[RankMatchSnapshotRecord]) -> None:
		if not rooms:
			return

		stmt = pg_insert(RankMatchSnapshotRow).values([
			dict(
				room_id=room.room_id,
				created_dt=room.created_dt,
				rank_id=room.rank_id,
				user1_npid=room.user1_npid,
				user1_online_name=room.user1_online_name,
				user2_npid=room.user2_npid,
				user2_online_name=room.user2_online_name,
			)
			for room in rooms
		]).on_conflict_do_nothing(index_elements=["room_id"])
		await session.execute(stmt)
		await session.flush()

		# Upsert hourly stats
		hour_key = _kst_hour_key()
		stmt = pg_insert(HourlyStatsRow).values(
			hour_key=hour_key,
			total_players=len(rooms) * 2,
			total_rooms=len(rooms),
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

	async def get_hourly_activity(self, session: AsyncSession, days: int = 7) -> list[HourlyActivity]:
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

		result = await session.execute(stmt)
		result_map = {
			row.hour: HourlyActivity(hour=row.hour, avg_players=float(row.avg_players), peak_players=row.peak_players)
			for row in result
		}

		return [
			result_map.get(h, HourlyActivity(hour=h, avg_players=0, peak_players=0))
			for h in range(24)
		]

	async def get_daily_summary(self, session: AsyncSession, days: int = 30) -> list[DailySummary]:
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

		result = await session.execute(stmt)
		return [
			DailySummary(date=row.date, peak_players=row.peak_players, avg_players=float(row.avg_players), peak_rooms=row.peak_rooms)
			for row in result
		]

	# -- Read: per-player stats ----------------------------------------------

	async def get_player_stats(self, session: AsyncSession, npid: str, days: int = 30) -> PlayerStats:
		cutoff = func.now() - timedelta(days=days)

		player_snapshots = (
			select(RankMatchSnapshotRow.room_id, RankMatchSnapshotRow.created_dt,
				   RankMatchSnapshotRow.user1_npid, RankMatchSnapshotRow.user2_npid,
				   RankMatchSnapshotRow.user1_online_name, RankMatchSnapshotRow.user2_online_name)
			.where(
				or_(RankMatchSnapshotRow.user1_npid == npid, RankMatchSnapshotRow.user2_npid == npid),
				RankMatchSnapshotRow.created_dt >= cutoff,
			)
			.subquery()
		)

		stats_stmt = select(
			func.count(func.distinct(func.cast(player_snapshots.c.created_dt, DateTime))).label("days_active"),
			func.count().label("times_seen"),
			func.min(player_snapshots.c.created_dt).label("first_seen"),
			func.max(player_snapshots.c.created_dt).label("last_seen"),
		)

		co_stmt = (
			select(
				case(
					(player_snapshots.c.user1_npid == npid, player_snapshots.c.user2_npid),
					else_=player_snapshots.c.user1_npid,
				).label("npid"),
				case(
					(player_snapshots.c.user1_npid == npid, player_snapshots.c.user2_online_name),
					else_=player_snapshots.c.user1_online_name,
				).label("online_name"),
				func.count().label("times_together"),
			)
			.group_by("npid","online_name")
			.order_by(func.count().desc())
			.limit(4)
		)

		row = (await session.execute(stats_stmt)).one_or_none()
		top_rows = (await session.execute(co_stmt)).all()

		cutoff_hours = func.now() - timedelta(days=7)
		hours_stmt = (
			select(
				func.extract("hour", func.timezone("Asia/Seoul", RankMatchSnapshotRow.created_dt)).cast(Integer).label("hour"),
				func.count(func.distinct(func.cast(func.timezone("Asia/Seoul", RankMatchSnapshotRow.created_dt), DateTime))).label("day_count"),
			)
			.where(
				or_(RankMatchSnapshotRow.user1_npid == npid, RankMatchSnapshotRow.user2_npid == npid),
				RankMatchSnapshotRow.created_dt >= cutoff_hours,
			)
			.group_by("hour")
		)
		hours_result = await session.execute(hours_stmt)
		active_hours = sorted(row.hour for row in hours_result if row.day_count >= 2)

		return PlayerStats(
			npid=npid,
			days_active=row.days_active if row else 0,
			times_seen=row.times_seen if row else 0,
			first_seen=row.first_seen if row else None,
			last_seen=row.last_seen if row else None,
			room_type_counts={},
			top_played_with=[
				CoPlayer(npid=r.npid, online_name=r.online_name, times_together=r.times_together)
				for r in top_rows
			],
			active_hours=active_hours,
		)

	async def get_weekly_top_players(self, session: AsyncSession, limit: int = 10) -> list[TopPlayer]:
		cutoff = func.now() - timedelta(days=7)

		user1_q = select(
			RankMatchSnapshotRow.user1_npid.label("npid"),
			RankMatchSnapshotRow.user1_online_name.label("online_name"),
		).where(RankMatchSnapshotRow.created_dt >= cutoff)

		user2_q = select(
			RankMatchSnapshotRow.user2_npid.label("npid"),
			RankMatchSnapshotRow.user2_online_name.label("online_name"),
		).where(RankMatchSnapshotRow.created_dt >= cutoff)

		sub = union_all(user1_q, user2_q).subquery()
		stmt = (
			select(
				sub.c.npid,
				func.max(sub.c.online_name).label("online_name"),
				func.count().label("match_count"),
			)
			.group_by(sub.c.npid)
			.order_by(func.count().desc())
			.limit(limit)
		)

		result = await session.execute(stmt)
		return [
			TopPlayer(npid=row.npid, online_name=row.online_name, match_count=row.match_count)
			for row in result
		]

