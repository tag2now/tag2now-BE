"""Fixtures for matching unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import matching.matchmaking_tracker as tracker_mod


@pytest.fixture(autouse=True)
def reset_matchmaking_state():
    yield
    tracker_mod._prev_rooms = None
    tracker_mod._searching_players = {}


@pytest.fixture(autouse=True)
def nobody_live(monkeypatch):
    # The room list asks streaming who is live; these tests have no database behind it.
    streaming = AsyncMock()
    streaming.live_for.return_value = {}
    monkeypatch.setattr("matching.service._streaming", streaming)
    return streaming.live_for


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
