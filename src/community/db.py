"""Community repository factory and lifecycle."""

import logging

from community.ports import CommunityRepository
from shared.settings import get_settings

logger = logging.getLogger(__name__)

_repo: CommunityRepository | None = None


def _create_repo() -> CommunityRepository:
    settings = get_settings()
    db_type = settings.db_type

    if db_type == "postgresql":
        from community.adapters.postgresql import PostgresCommunityRepository
        return PostgresCommunityRepository(dsn=settings.db_url)

    if db_type == "dynamodb":
        from community.adapters.dynamodb import DynamoCommunityRepository
        return DynamoCommunityRepository(
            region=settings.dynamodb_region,
            table_name=settings.dynamodb_table_name,
            endpoint_url=settings.dynamodb_endpoint_url,
        )

    raise ValueError(f"Unknown db_type: {db_type!r}")


async def init_db():
    global _repo
    _repo = _create_repo()
    await _repo.init()


async def close_db():
    global _repo
    if _repo:
        await _repo.close()
        _repo = None


def get_repo() -> CommunityRepository:
    if _repo is None:
        raise RuntimeError("Community repository not initialized — call init_db() first")
    return _repo
