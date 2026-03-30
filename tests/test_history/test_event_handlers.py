"""Tests for history.event_handlers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from history.event_handlers import _to_snapshot_record
from matching.models import Rank, RoomInfoDTO, RoomType


def test_to_snapshot_record_basic():
    room = RoomInfoDTO.phantom("p1", "Player1", RoomType.RANK_MATCH, None)
    record = _to_snapshot_record(room)
    assert record.is_matchmaking is True  # room_id == 0
    assert record.owner_npid == "p1"
    assert "p1" in record.member_npids


def test_to_snapshot_record_with_users():
    ri = SimpleNamespace(
        room_id=5, owner_npid="p1", owner_online_name="P1",
        current_members=2, max_slots=4,
        int_attrs={4: SimpleNamespace(value=1)},
        users=[SimpleNamespace(user_id="p2", online_name="P2")],
    )
    room = RoomInfoDTO(ri)
    record = _to_snapshot_record(room)
    assert "p1" in record.member_npids
    assert "p2" in record.member_npids
    assert record.member_npids.count("p1") == 1


def test_to_snapshot_record_nonzero_room_id():
    ri = SimpleNamespace(
        room_id=99, owner_npid="p1", owner_online_name="P1",
        current_members=1, max_slots=2,
        int_attrs={4: SimpleNamespace(value=0)},
        users=[],
    )
    room = RoomInfoDTO(ri)
    record = _to_snapshot_record(room)
    assert record.is_matchmaking is False
    assert record.room_id == 99


@pytest.mark.asyncio
async def test_handle_activity_snapshot_calls_service():
    from history.event_handlers import _handle_activity_snapshot
    from matching.events import ActivitySnapshot

    room = RoomInfoDTO.phantom("p1", "P1", RoomType.RANK_MATCH, None)
    event = ActivitySnapshot(rooms=[room])

    with patch("history.service.record_snapshot", new_callable=AsyncMock) as mock_record:
        await _handle_activity_snapshot(event)
        mock_record.assert_called_once()
        snapshots = mock_record.call_args[0][0]
        assert len(snapshots) == 1
        assert snapshots[0].owner_npid == "p1"
