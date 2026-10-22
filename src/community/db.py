"""Community repository factory and lifecycle."""

import logging

from community.adapters.postgresql import PostgresCommunityRepository
from community.ports import CommunityRepository

logger = logging.getLogger(__name__)

_repo: CommunityRepository | None = None


async def init_db():
    global _repo
    _repo = PostgresCommunityRepository()
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
