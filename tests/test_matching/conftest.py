"""Fixtures for the matching module tests."""

import os
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("RPCN_USER", "test")
os.environ.setdefault("RPCN_PASSWORD", "test")
os.environ.setdefault("RPCN_TOKEN", "test")
os.environ.setdefault("RPCN_HOST", "localhost")
os.environ.setdefault("RPCN_PORT", "31313")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DB_URL", "localhost:5432")

from matching.models import Rank, RoomInfoDTO, RoomType
import matching.matchmaking_tracker as tracker_mod
import shared.events as events_mod


@pytest.fixture(autouse=True)
def reset_matchmaking_state():
    yield
    tracker_mod._prev_rooms = {}
    tracker_mod._matchmaking_players = {}


@pytest.fixture(autouse=True)
def reset_event_bus():
    yield
    events_mod._handlers = defaultdict(list)


@pytest.fixture
def make_phantom_room():
    def _factory(npid="player1", name="Player1", room_type=RoomType.RANK_MATCH, rank_info=None):
        return RoomInfoDTO.phantom(npid, name, room_type, rank_info)
    return _factory


@pytest.fixture
def mock_publish(monkeypatch):
    events = []
    monkeypatch.setattr("matching.matchmaking_tracker.publish", lambda e: events.append(e))
    return events


@pytest.fixture
def mock_settings(monkeypatch):
    settings = MagicMock()
    settings.matchmaking_ttl = 60
    monkeypatch.setattr("matching.matchmaking_tracker.get_settings", lambda: settings)
    return settings


@pytest.fixture
def mock_cache(monkeypatch):
    monkeypatch.setattr("matching.service.cache_get", lambda key: None)
    monkeypatch.setattr("matching.service.cache_set", lambda key, value, ttl: None)
