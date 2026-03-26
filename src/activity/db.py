"""Activity repository factory and lifecycle."""

import logging

from activity.ports import ActivityPort
from shared.settings import get_settings

logger = logging.getLogger(__name__)

_repo: ActivityPort | None = None


def _create_repo() -> ActivityPort:
    from activity.adapters.dynamodb import DynamoActivityAdapter
    settings = get_settings()
    return DynamoActivityAdapter(table_name=settings.dynamodb_activity_table_name)


async def init_activity_repo() -> None:
    global _repo
    _repo = _create_repo()
    await _repo.init()


async def close_activity_repo() -> None:
    global _repo
    if _repo:
        await _repo.close()
        _repo = None


def get_activity_repo() -> ActivityPort:
    if _repo is None:
        raise RuntimeError("Activity repository not initialized — call init_activity_repo() first")
    return _repo
