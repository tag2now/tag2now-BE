"""Tests for application startup and shutdown orchestration."""

import asyncio
import importlib
import sys

import pytest


@pytest.fixture
def app_module(monkeypatch):
    import shared.cache

    monkeypatch.setattr(shared.cache, "redis_health_check", lambda: None)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


async def test_lifespan_runs_the_collector_between_startup_and_shutdown(app_module, monkeypatch):
    events = []
    container = object()

    async def build_container(stack):
        events.append("built")
        stack.push_async_callback(_record, events, "closed")
        return container

    started = asyncio.Event()

    async def collector():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append("collector stopped")

    monkeypatch.setattr(app_module, "build_container", build_container)
    monkeypatch.setattr(app_module, "run_collector", collector)

    async with app_module.lifespan(app_module.app):
        await asyncio.wait_for(started.wait(), timeout=0.1)
        assert app_module.app.state.container is container

    # The collector reads through services, so it stops before they close.
    assert events == ["built", "collector stopped", "closed"]


async def test_a_failing_startup_closes_what_it_had_opened(app_module, monkeypatch):
    events = []

    async def build_container(stack):
        stack.push_async_callback(_record, events, "closed")
        raise RuntimeError("database unreachable")

    async def collector():
        events.append("collector started")

    monkeypatch.setattr(app_module, "build_container", build_container)
    monkeypatch.setattr(app_module, "run_collector", collector)

    with pytest.raises(RuntimeError, match="database unreachable"):
        async with app_module.lifespan(app_module.app):
            pass

    assert events == ["closed"]


async def _record(events, event):
    events.append(event)
