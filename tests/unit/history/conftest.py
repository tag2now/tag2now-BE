"""Fixtures for history unit tests."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from history.ports import HistoryPort
from history.service import HistoryService


@pytest.fixture
def repo():
    return AsyncMock(spec=HistoryPort)


@pytest.fixture
def session():
    """A session whose `begin()` works as `async with`."""
    session = MagicMock()

    @asynccontextmanager
    async def begin():
        yield

    session.begin = begin
    return session


@pytest.fixture
def service(repo, session):
    @asynccontextmanager
    async def sessions():
        yield session

    return HistoryService(repo, sessions)
