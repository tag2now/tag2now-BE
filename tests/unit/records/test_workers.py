"""The background loops: they survive failures, and sleep only when there is nothing to do."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from records import workers


@pytest.fixture
def sleep(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(workers.asyncio, "sleep", sleep)
    return sleep


@pytest.fixture
def settings(monkeypatch):
    settings = MagicMock(
        save_admin_url="http://save-admin", save_capture_interval_seconds=10, match_event_idle_seconds=5
    )
    monkeypatch.setattr(workers, "get_settings", lambda: settings)
    return settings


async def test_capture_is_off_without_a_save_server(settings):
    settings.save_admin_url = ""
    records = MagicMock(capture=AsyncMock())
    await workers.SaveCapture(records).run()
    records.capture.assert_not_awaited()


async def test_capture_goes_on_after_a_failure(settings, sleep):
    records = MagicMock(capture=AsyncMock(side_effect=[RuntimeError("save-admin down"), None, asyncio.CancelledError]))
    with pytest.raises(asyncio.CancelledError):
        await workers.SaveCapture(records).run()
    assert records.capture.await_count == 3
    assert [call.args for call in sleep.await_args_list] == [(10,), (10,)]


async def test_consumer_sleeps_only_when_the_queue_is_empty(settings, sleep):
    records = MagicMock(process_next=AsyncMock(side_effect=[True, True, False, asyncio.CancelledError]))
    with pytest.raises(asyncio.CancelledError):
        await workers.EventConsumer(records).run()
    assert [call.args for call in sleep.await_args_list] == [(5,)]


async def test_consumer_goes_on_after_a_failure(settings, sleep):
    records = MagicMock(process_next=AsyncMock(side_effect=[RuntimeError("database down"), asyncio.CancelledError]))
    with pytest.raises(asyncio.CancelledError):
        await workers.EventConsumer(records).run()
    assert sleep.await_count == 1
