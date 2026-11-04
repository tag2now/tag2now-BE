"""Tests for application startup and shutdown orchestration."""

import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def app_module(monkeypatch):
    import shared.cache

    monkeypatch.setattr(shared.cache, "redis_health_check", lambda: None)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


async def test_lifespan_runs_the_workers_between_startup_and_shutdown(app_module, monkeypatch):
    events = []
    started = {name: asyncio.Event() for name in ("collector", "save_capture", "event_consumer")}

    def worker(name):
        async def run():
            started[name].set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append(f"{name} stopped")

        return SimpleNamespace(run=run)

    container = SimpleNamespace(**{name: worker(name) for name in started})

    async def build_container(stack):
        events.append("built")
        stack.push_async_callback(_record, events, "closed")
        return container

    monkeypatch.setattr(app_module, "build_container", build_container)

    async with app_module.lifespan(app_module.app):
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=0.1)
        assert app_module.app.state.container is container

    # The workers read through services, so all of them stop before those close.
    assert events[0] == "built" and events[-1] == "closed"
    assert sorted(events[1:-1]) == sorted(f"{name} stopped" for name in started)


async def test_a_failing_startup_closes_what_it_had_opened(app_module, monkeypatch):
    events = []

    async def build_container(stack):
        stack.push_async_callback(_record, events, "closed")
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(app_module, "build_container", build_container)

    with pytest.raises(RuntimeError, match="database unreachable"):
        async with app_module.lifespan(app_module.app):
            pass

    assert events == ["closed"]


async def _record(events, event):
    events.append(event)
