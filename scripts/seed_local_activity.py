"""Seed the local database with players whose sessions cross the day boundary.

The statistics day runs 06:00 KST to 06:00 KST, and the cases that boundary
exists for --- a session that starts late and ends after midnight --- do not
occur in a freshly collected local database, so there is nothing local to look
at while changing how days are cut. This writes those cases by hand.

Local only. It talks to whatever `env/.env.local` points at, and it deletes its
own rows first so re-running leaves one copy rather than a growing pile.

Seeded rows are identified by their room_id, which is reserved from SEED_ROOM_ID
up --- never by npid. One of the players seeded here is real and already has real
rows in this database; keying the cleanup on the name would delete those too.

    .venv/Scripts/python.exe scripts/seed_local_activity.py
    .venv/Scripts/python.exe scripts/seed_local_activity.py --clean
"""

import argparse
import asyncio
import sys
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import delete, select

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))

from history.adapters.postgresql import stat_day  # noqa: E402
from history.entities import RankMatchSnapshotRow  # noqa: E402
from shared.database import close_database, get_session_factory, init_database  # noqa: E402

KST = timezone(timedelta(hours=9))

# A night owl whose session runs past midnight, a player who stops before the
# boundary, and one who starts right after it --- the three ways a session can
# sit against a 06:00 cut.
NIGHT_OWL = "seed-night-owl"
DAWN_QUITTER = "seed-dawn-quitter"
EARLY_BIRD = "seed-early-bird"

# A real player, seeded with the hours they actually play. Their own rows sit on
# one day nine days back, which is outside the seven-day window active_hours
# reads and short of the two days it requires, so the panel shows them nothing.
# These rows repeat that same pattern on recent days to make it render.
REAL_NIGHT_OWL = "doStudyy"

# active_hours only reports an hour seen on two distinct days, so each player
# needs the same hours on more than one day to show up at all.
SESSIONS = {
	NIGHT_OWL: [22, 23, 0, 1, 2],
	DAWN_QUITTER: [3, 4, 5],
	EARLY_BIRD: [6, 7, 8],
	REAL_NIGHT_OWL: [22, 23, 0, 1],
}
DAYS = 3
OPPONENT = "seed-opponent"

# Room ids this script owns. RPCN's own ids restart at 1 with the server and
# never come near this, so the range identifies a seeded row unambiguously.
SEED_ROOM_ID = 900000


def _sessions_for(npid: str, hours: list[int], today: datetime, slot: int) -> list[dict]:
	"""One room per hour per day, walking back from yesterday."""
	rows = []
	for day_offset in range(1, DAYS + 1):
		# Anchor on the statistics day, so an hour after midnight lands on the
		# following calendar date --- which is what makes it the same play day.
		day_start = datetime.combine(today - timedelta(days=day_offset), time(6), tzinfo=KST)
		for hour in hours:
			moment = day_start + timedelta(hours=(hour - 6) % 24)
			rows.append(dict(
				room_id=SEED_ROOM_ID + slot * 1000 + day_offset * 100 + hour,
				created_dt=moment.astimezone(timezone.utc),
				match_date=stat_day(moment),
				rank_id=10,
				user1_npid=npid,
				user1_online_name=npid,
				user2_npid=OPPONENT,
				user2_online_name=OPPONENT,
			))
	return rows


async def _clean(session) -> int:
	result = await session.execute(delete(RankMatchSnapshotRow).where(
		RankMatchSnapshotRow.room_id >= SEED_ROOM_ID
	))
	return result.rowcount or 0


async def main(clean_only: bool) -> None:
	await init_database()
	factory = get_session_factory()
	async with factory() as session:
		async with session.begin():
			removed = await _clean(session)
			print(f"removed {removed} previously seeded rows")
			if clean_only:
				return

			today = stat_day(datetime.now(timezone.utc))
			rows = [
				row
				for slot, (npid, hours) in enumerate(SESSIONS.items())
				for row in _sessions_for(npid, hours, today, slot)
			]
			session.add_all([RankMatchSnapshotRow(**row) for row in rows])

		async with session.begin():
			for npid, hours in SESSIONS.items():
				seeded = len((await session.execute(select(RankMatchSnapshotRow).where(
					RankMatchSnapshotRow.user1_npid == npid,
					RankMatchSnapshotRow.room_id >= SEED_ROOM_ID,
				))).scalars().all())
				print(f"{npid:18} hours {hours} over {DAYS} days -> {seeded} seeded rows")
	await close_database()


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--clean", action="store_true", help="remove seeded rows and exit")
	asyncio.run(main(parser.parse_args().clean))
