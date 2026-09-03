"""Tests for application startup and shutdown orchestration."""

import asyncio
import importlib
import sys
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_the_match_history_collector(monkeypatch):
    import shared.cache

    monkeypatch.setattr(shared.cache, "redis_health_check", lambda: None)
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")

    initializers = ["init_database", "init_db", "init_reservation_db", "init_history_repo", "init_game_repo"]
    closers = ["close_game_repo", "close_history_repo", "close_reservation_db", "close_db", "close_database"]
    mocks = {name: AsyncMock() for name in initializers + closers}
    for name, mock in mocks.items():
        monkeypatch.setattr(app_module, name, mock)

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def collector():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(app_module, "run_collector", collector)

    async with app_module.lifespan(app_module.app):
        await asyncio.wait_for(started.wait(), timeout=0.1)

    await asyncio.wait_for(cancelled.wait(), timeout=0.1)
    for name in initializers + closers:
        mocks[name].assert_awaited_once()
