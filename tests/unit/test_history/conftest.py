"""Fixtures for history unit tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from history.models import RoomSnapshotRecord
from history.ports import HistoryPort


@pytest.fixture
def mock_history_repo(monkeypatch):
    repo = AsyncMock(spec=HistoryPort)
    monkeypatch.setattr("history.service.get_history_repo", lambda: repo)
    return repo


@pytest.fixture
def mock_cache(monkeypatch):
    monkeypatch.setattr("history.service.cache_get", lambda key: None)
    monkeypatch.setattr("history.service.cache_set", lambda key, value, ttl: None)


@pytest.fixture
def sample_snapshot_record():
    def _factory(**overrides):
        defaults = dict(
            room_id=100,
            room_type="rank_match",
            owner_npid="player1",
            owner_online_name="Player1",
            current_members=1,
            max_slots=2,
            is_matchmaking=False,
            member_npids=["player1"],
            member_online_names=["Player1"],
        )
        defaults.update(overrides)
        return RoomSnapshotRecord(**defaults)
    return _factory
