"""DynamoDB adapter for the ActivityPort."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from activity.ports import ActivityPort
from shared.dynamo import DynamoTableConnection

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


class DynamoActivityAdapter(ActivityPort):
    """ActivityPort backed by a DynamoDB table."""

    def __init__(self, table_name: str):
        self._table_name = table_name
        self._conn = DynamoTableConnection(table_name)

    async def init(self) -> None:
        await self._conn.init(create_table_fn=self._create_table)
        logger.info("Activity tracker DynamoDB table '%s' ready", self._table_name)

    @staticmethod
    async def _create_table(resource, table_name: str):
        logger.info("Creating activity tracker table '%s'", table_name)
        table = await resource.create_table(TableName=table_name, **_TABLE_SCHEMA)
        await table.wait_until_exists()
        logger.info("Activity tracker table '%s' created", table_name)
        return table

    async def close(self) -> None:
        await self._conn.close()
        logger.info("Activity tracker DynamoDB resource closed")

    async def record_activity(self, player_npids: list[str], total_players: int) -> None:
        sk = _kst_hour_key()

        try:
            await self._conn.table.update_item(
                Key={"PK": "ACTIVITY#GLOBAL", "SK": sk},
                UpdateExpression="SET player_count = :cnt",
                ConditionExpression="attribute_not_exists(player_count) OR player_count < :cnt",
                ExpressionAttributeValues={":cnt": total_players},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

        for npid in player_npids:
            await self._conn.table.put_item(
                Item={"PK": f"ACTIVITY#PLAYER#{npid}", "SK": sk, "seen": 1},
            )

    async def get_global_activity(self) -> list[dict]:
        start_sk, end_sk = _sk_range_last_n_days()
        resp = await self._conn.table.query(
            KeyConditionExpression="PK = :pk AND SK BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":pk": "ACTIVITY#GLOBAL",
                ":start": start_sk,
                ":end": end_sk,
            },
        )

        hour_counts: dict[int, list[int]] = defaultdict(list)
        for item in resp.get("Items", []):
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

    async def get_player_hours(self, npid: str) -> list[int]:
        start_sk, end_sk = _sk_range_last_n_days()
        resp = await self._conn.table.query(
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

        return sorted(h for h, days in hour_days.items() if len(days) >= 2)
