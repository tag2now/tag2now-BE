"""PostgreSQL adapter for the history module using SQLAlchemy ORM."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, delete, func, or_, select, text, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from history.entities import HourlyStatsRow, RoomSnapshotRow, SnapshotMemberRow
from history.models import CoPlayer, DailySummary, HourlyActivity, PlayerStats, RoomSnapshotRecord, TopPlayer
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

	async def record_snapshot(self, session: AsyncSession, rooms: list[RoomSnapshotRecord]) -> None:
		if not rooms:
			return

		total_players = sum(r.current_members for r in rooms)
		total_rooms = len(rooms)

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

		await session.flush()

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

		co_members_q = (
			select(SnapshotMemberRow.npid, SnapshotMemberRow.online_name)
			.where(
				SnapshotMemberRow.snapshot_id.in_(select(player_snapshots.c.id)),
				SnapshotMemberRow.npid != npid,
			)
		)
		co_owners_q = (
			select(
				RoomSnapshotRow.owner_npid.label("npid"),
				RoomSnapshotRow.owner_online_name.label("online_name"),
			)
			.where(
				RoomSnapshotRow.id.in_(select(player_snapshots.c.id)),
				RoomSnapshotRow.owner_npid != npid,
			)
		)
		co_union = union_all(co_members_q, co_owners_q).subquery()
		top_stmt = (
			select(
				co_union.c.npid,
				co_union.c.online_name,
				func.count().label("times_together"),
			)
			.group_by(co_union.c.npid, co_union.c.online_name)
			.order_by(func.count().desc())
			.limit(5)
		)

		row = (await session.execute(stats_stmt)).one_or_none()
		type_rows = (await session.execute(type_stmt)).all()
		top_rows = (await session.execute(top_stmt)).all()

		return PlayerStats(
			npid=npid,
			days_active=row.days_active if row else 0,
			times_seen=row.times_seen if row else 0,
			first_seen=row.first_seen if row else None,
			last_seen=row.last_seen if row else None,
			room_type_counts={r.room_type: r.cnt for r in type_rows},
			top_played_with=[
				CoPlayer(npid=r.npid, online_name=r.online_name, times_together=r.times_together)
				for r in top_rows
			],
		)

	async def get_weekly_top_players(self, session: AsyncSession, limit: int = 10) -> list[TopPlayer]:
		cutoff = func.now() - timedelta(days=7)

		owners_q = select(
			RoomSnapshotRow.owner_npid.label("npid"),
			RoomSnapshotRow.owner_online_name.label("online_name"),
		).where(RoomSnapshotRow.captured_at >= cutoff)

		members_q = select(
			SnapshotMemberRow.npid,
			SnapshotMemberRow.online_name,
		).join(RoomSnapshotRow, RoomSnapshotRow.id == SnapshotMemberRow.snapshot_id).where(
			RoomSnapshotRow.captured_at >= cutoff
		)

		sub = union_all(owners_q, members_q).subquery()
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

	async def get_player_hours(self, session: AsyncSession, npid: str, days: int = 7) -> list[int]:
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

		result = await session.execute(stmt)
		return sorted(row.hour for row in result if row.day_count >= 2)
