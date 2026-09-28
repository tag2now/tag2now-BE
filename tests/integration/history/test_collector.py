"""Integration tests for the match-history collector against PostgreSQL.

RPCN is stubbed; the collector, history service, adapter and the table's
unique key are real. The service commits, so rows are removed by npid.
Run with: pytest tests/integration/history/ -v
"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, or_, select

from history.entities import RankMatchSnapshotRow
from shared.database import close_database, get_session_factory, init_database

_NPIDS = ["collector-p1", "collector-p2"]


def _in_test_rows():
    return or_(RankMatchSnapshotRow.user1_npid.in_(_NPIDS), RankMatchSnapshotRow.user2_npid.in_(_NPIDS))


async def _delete_test_rows():
    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(RankMatchSnapshotRow).where(_in_test_rows()))


async def _count_test_rows() -> int:
    async with get_session_factory()() as session:
        return (await session.execute(
            select(func.count()).select_from(RankMatchSnapshotRow).where(_in_test_rows())
        )).scalar_one()


@pytest_asyncio.fixture
async def collector(monkeypatch):
    """The real collector over a stubbed RPCN, with only rank-match writes live."""
    from history import collector as collector_mod
    from history.db import close_history_repo, init_history_repo
    from matching.models import ActivityObservation, Rank, RoomInfoDTO, RoomType
    from rpcn_client.models import UserInfo

    await init_database()
    await init_history_repo()
    await _delete_test_rows()

    room = RoomInfoDTO.phantom(_NPIDS[0], "P1", RoomType.RANK_MATCH, Rank(id=10))
    room.room_id = 424242
    room.current_members = 2
    room.users = [UserInfo(npid=npid, online_name=npid, avatar_url="") for npid in _NPIDS]
    observation = ActivityObservation(
        rank_player_npids=set(_NPIDS), total_players=2, total_rooms=1,
        rank_players=2, rank_rooms=1, rank_matches=[room],
    )
    monkeypatch.setattr(collector_mod, "collect_activity_observation", AsyncMock(return_value=observation))
    monkeypatch.setattr(collector_mod.history_service, "record_daily_matched_players", AsyncMock())
    monkeypatch.setattr(collector_mod.history_service, "record_activity_snapshot", AsyncMock())
    monkeypatch.setattr(collector_mod, "_prev_rank_match_ids", set())

    yield collector_mod

    await _delete_test_rows()
    await close_history_repo()
    await close_database()


@pytest.mark.asyncio
async def test_a_match_in_progress_across_cycles_is_stored_once(collector):
    await collector.collect_once()
    await collector.collect_once()

    assert await _count_test_rows() == 1


@pytest.mark.asyncio
async def test_a_match_seen_again_after_a_restart_is_stored_once(collector, monkeypatch):
    """A restart empties the in-memory diff; the table's unique key must still hold."""
    await collector.collect_once()
    monkeypatch.setattr(collector, "_prev_rank_match_ids", set())
    await collector.collect_once()

    assert await _count_test_rows() == 1
