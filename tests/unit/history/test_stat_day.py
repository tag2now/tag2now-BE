"""The 06:00-KST statistics day boundary."""

from datetime import date, datetime, timedelta, timezone

import pytest

from history.adapters.postgresql import STAT_DAY_START_HOUR, stat_day, stat_day_start

KST = timezone(timedelta(hours=9))


@pytest.mark.parametrize("kst_moment, expected", [
	(datetime(2026, 9, 16, 6, 0, tzinfo=KST), date(2026, 9, 16)),
	(datetime(2026, 9, 16, 23, 59, tzinfo=KST), date(2026, 9, 16)),
	(datetime(2026, 9, 17, 0, 0, tzinfo=KST), date(2026, 9, 16)),
	(datetime(2026, 9, 17, 3, 30, tzinfo=KST), date(2026, 9, 16)),
	(datetime(2026, 9, 17, 5, 59, tzinfo=KST), date(2026, 9, 16)),
	(datetime(2026, 9, 17, 6, 0, tzinfo=KST), date(2026, 9, 17)),
])
def test_a_late_night_session_stays_on_the_day_it_started(kst_moment, expected):
	assert stat_day(kst_moment) == expected


def test_stat_day_reads_the_moment_in_kst_whatever_zone_it_arrives_in():
	utc_moment = datetime(2026, 9, 16, 19, 0, tzinfo=timezone.utc)  # 2026-09-17 04:00 KST
	assert stat_day(utc_moment) == date(2026, 9, 16)


def test_stat_day_start_is_six_kst_of_that_day():
	assert stat_day_start(date(2026, 9, 16)) == datetime(2026, 9, 16, 6, tzinfo=KST)


def test_a_day_starts_where_the_previous_one_ends():
	day = date(2026, 9, 16)
	assert stat_day(stat_day_start(day)) == day
	assert stat_day(stat_day_start(day) - timedelta(seconds=1)) == day - timedelta(days=1)


def test_every_instant_of_a_day_maps_back_to_it():
	day = date(2026, 9, 16)
	start = stat_day_start(day)
	assert {stat_day(start + timedelta(hours=h)) for h in range(24)} == {day}
	assert STAT_DAY_START_HOUR == 6
