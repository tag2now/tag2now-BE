"""Fixtures for history unit tests."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from history.models import RoomSnapshotRecord
from history.ports import HistoryPort


@pytest.fixture
def mock_session():
    """A mock AsyncSession that supports 'async with session.begin()'."""
    session = AsyncMock()

    @asynccontextmanager
    async def _fake_begin():
        yield

    session.begin = _fake_begin
    return session


@pytest.fixture
def mock_session_factory(monkeypatch, mock_session):
    """Mock get_session_factory so decorators don't need a real DB."""
    @asynccontextmanager
    async def _fake_session():
        yield mock_session

    def factory():
        return _fake_session()

    monkeypatch.setattr("shared.database.get_session_factory", lambda: factory)
    return factory


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
