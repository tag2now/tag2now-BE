"""Track player activity in DynamoDB for global and per-player stats.

DynamoDB key layout (dedicated activity table):
  Global hourly:  PK=ACTIVITY#GLOBAL          SK=2026-03-25T14  (KST hour)
  Per-player:     PK=ACTIVITY#PLAYER#{npid}   SK=2026-03-25T14  (KST hour)
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from shared.dynamo import DynamoTableConnection
from shared.settings import get_settings

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
_RETENTION_DAYS = 7

_TABLE_SCHEMA = {
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
}


async def _create_table(resource, table_name: str):
    logger.info("Creating activity tracker table '%s'", table_name)
    table = await resource.create_table(TableName=table_name, **_TABLE_SCHEMA)
    await table.wait_until_exists()
    logger.info("Activity tracker table '%s' created", table_name)
    return table


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_conn: DynamoTableConnection | None = None


async def init() -> None:
    global _conn
    settings = get_settings()
    _conn = DynamoTableConnection(settings.dynamodb_activity_table_name)
    await _conn.init(create_table_fn=_create_table)
    logger.info("Activity tracker DynamoDB table '%s' ready", settings.dynamodb_activity_table_name)


async def close() -> None:
    global _conn
    if _conn:
        await _conn.close()
        _conn = None
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
        await _conn.table.update_item(
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
        await _conn.table.put_item(
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
    resp = await _conn.table.query(
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

    Returns sorted list of hours when the player was seen on 2+ distinct days.
    """
    start_sk, end_sk = _sk_range_last_n_days()
    resp = await _conn.table.query(
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

    # Return hours when player appeared on at least 2 different days
    return sorted(h for h, days in hour_days.items() if len(days) >= 2)
