from datetime import datetime, timezone

import pytest

from chat.domain import KST, day_start


@pytest.mark.parametrize(
    "now, expected",
    [
        # 23:00 KST belongs to the day that opened at 06:00 the same date.
        (datetime(2026, 10, 7, 23, 0, tzinfo=KST), datetime(2026, 10, 7, 6, 0, tzinfo=KST)),
        # 01:00 KST is still the previous evening's session.
        (datetime(2026, 10, 8, 1, 0, tzinfo=KST), datetime(2026, 10, 7, 6, 0, tzinfo=KST)),
        # 06:00 sharp opens a new day.
        (datetime(2026, 10, 8, 6, 0, tzinfo=KST), datetime(2026, 10, 8, 6, 0, tzinfo=KST)),
        (datetime(2026, 10, 8, 5, 59, 59, tzinfo=KST), datetime(2026, 10, 7, 6, 0, tzinfo=KST)),
    ],
)
def test_day_start_is_the_last_0600_kst(now, expected):
    assert day_start(now) == expected


def test_day_start_answers_in_the_zone_it_was_asked_in():
    now = datetime(2026, 10, 7, 20, 30, tzinfo=timezone.utc)  # 05:30 KST on the 8th

    start = day_start(now)

    assert start.tzinfo == timezone.utc
    assert start == datetime(2026, 10, 6, 21, 0, tzinfo=timezone.utc)  # 06:00 KST on the 7th
