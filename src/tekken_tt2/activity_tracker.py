"""Track player activity in DynamoDB for global and per-player stats.

DynamoDB key layout (same table as community):
  Global hourly:  PK=ACTIVITY#GLOBAL          SK=2026-03-25T14  (KST hour)
  Per-player:     PK=ACTIVITY#PLAYER#{npid}   SK=2026-03-25T14  (KST hour)
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import aioboto3
from botocore.exceptions import ClientError

from shared.settings import get_settings

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
_RETENTION_DAYS = 7


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_session: aioboto3.Session | None = None
_resource_ctx = None
_resource = None
_table = None


async def init() -> None:
    global _session, _resource_ctx, _resource, _table
    settings = get_settings()
    session_kwargs = {}
    if settings.aws_access_key_id:
        session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    _session = aioboto3.Session(**session_kwargs)
    kwargs = {"region_name": settings.dynamodb_region}
    if settings.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
    _resource_ctx = _session.resource("dynamodb", **kwargs)
    _resource = await _resource_ctx.__aenter__()
    _table = await _resource.Table(settings.dynamodb_table_name)
    await _table.load()
    logger.info("Activity tracker DynamoDB table '%s' ready", settings.dynamodb_table_name)


async def close() -> None:
    global _resource_ctx, _resource, _table, _session
    if _resource_ctx:
        await _resource_ctx.__aexit__(None, None, None)
        _resource_ctx = None
        _resource = None
        _table = None
        _session = None
        logger.info("Activity tracker DynamoDB resource closed")


def _kst_hour_key() -> str:
    """Return the current KST date+hour as 'YYYY-MM-DDTHH'."""
    now = datetime.now(KST)
    return now.strftime("%Y-%m-%dT%H")


def _sk_range_last_n_days(days: int = _RETENTION_DAYS) -> tuple[str, str]:
    """Return (start_sk, end_sk) covering the last N days in KST."""
    now = datetime.now(KST)
    start = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H")
    end = now.strftime("%Y-%m-%dT%H")
    return start, end


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

async def record_activity(player_npids: list[str], total_players: int) -> None:
    """Record current snapshot: global player count + each player's presence."""
    sk = _kst_hour_key()

    # Global hourly — use MAX to keep peak count for this hour
    try:
        await _table.update_item(
            Key={"PK": "ACTIVITY#GLOBAL", "SK": sk},
            UpdateExpression="SET player_count = :cnt",
            ConditionExpression="attribute_not_exists(player_count) OR player_count < :cnt",
            ExpressionAttributeValues={":cnt": total_players},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    # Per-player: mark each player as seen this hour
    for npid in player_npids:
        await _table.put_item(
            Item={"PK": f"ACTIVITY#PLAYER#{npid}", "SK": sk, "seen": 1},
        )


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

async def get_global_activity() -> list[dict]:
    """Return avg player count per KST hour (0-23) over the last N days.

    Returns list of 24 dicts: {"hour": 0..23, "avg_players": float}
    """
    start_sk, end_sk = _sk_range_last_n_days()
    resp = await _table.query(
        KeyConditionExpression="PK = :pk AND SK BETWEEN :start AND :end",
        ExpressionAttributeValues={
            ":pk": "ACTIVITY#GLOBAL",
            ":start": start_sk,
            ":end": end_sk,
        },
    )

    hour_counts: dict[int, list[int]] = defaultdict(list)
    for item in resp.get("Items", []):
        # SK format: "2026-03-25T14"
        hour = int(item["SK"].split("T")[1])
        hour_counts[hour].append(int(item["player_count"]))

    return [
        {
            "hour": h,
            "avg_players": round(sum(counts) / len(counts), 1) if counts else 0,
        }
        for h in range(24)
        for counts in [hour_counts.get(h, [])]
    ]


async def get_player_hours(npid: str) -> list[int]:
    """Return KST hours (0-23) when this player is typically online (last N days).

    Returns sorted list of hours where the player was seen on 2+ distinct days.
    """
    start_sk, end_sk = _sk_range_last_n_days()
    resp = await _table.query(
        KeyConditionExpression="PK = :pk AND SK BETWEEN :start AND :end",
        ExpressionAttributeValues={
            ":pk": f"ACTIVITY#PLAYER#{npid}",
            ":start": start_sk,
            ":end": end_sk,
        },
    )

    hour_days: dict[int, set[str]] = defaultdict(set)
    for item in resp.get("Items", []):
        date_part, hour_part = item["SK"].split("T")
        hour_days[int(hour_part)].add(date_part)

    # Return hours where player appeared on at least 2 different days
    return sorted(h for h, days in hour_days.items() if len(days) >= 2)
