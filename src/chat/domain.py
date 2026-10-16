"""Chat shows the current play day and the one before it, and nothing longer.

A play day runs from 06:00 KST to the next 06:00 KST. The previous day stays
in view so a conversation does not look cut off just after 06:00. Older
messages are not shown, and nothing promises to keep them: the store is
process memory, so a deploy empties it as well.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# A play session ends at dawn, not at midnight --- the same boundary as the
# statistics day (history) and the booking window (reservation). At midnight a
# conversation running from 23:00 to 01:00 would be cut in half.
DAY_START_HOUR = 6


@dataclass(frozen=True)
class Message:
    id: int
    author_username: str
    author_online_name: str
    body: str
    created_at: datetime
    # Whether the author was an admin when they posted --- the token's claim,
    # read at that moment. The line keeps it for the rest of its one day.
    author_admin: bool = False


@dataclass(frozen=True)
class Posted:
    message: Message


@dataclass(frozen=True)
class Deleted:
    message_id: int


ChatEvent = Posted | Deleted


def day_start(now: datetime) -> datetime:
    """The 06:00 KST that opened the play day `now` falls in."""
    kst_now = now.astimezone(KST)
    start = kst_now.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
    if kst_now < start:
        start -= timedelta(days=1)
    return start.astimezone(now.tzinfo)


def history_start(now: datetime) -> datetime:
    """The oldest moment whose messages are still shown: the 06:00 KST that
    opened the previous play day."""
    return day_start(now) - timedelta(days=1)
