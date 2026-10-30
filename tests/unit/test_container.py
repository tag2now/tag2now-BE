"""The composition root opens modules in order and closes them in reverse."""

from contextlib import AsyncExitStack

import pytest

import container
from admin.service import AdminService
from auth.service import AuthService
from chat.service import ChatService
from community.service import CommunityService
from history.collector import Collector
from history.service import HistoryService
from matching.service import MatchingService
from reservation.service import ReservationService
from saves.service import SavesService
from streaming.service import StreamingService


def _lifecycles(calls, fail_at=None):
    def pair(i):
        async def init():
            calls.append(f"init{i}")
            if i == fail_at:
                raise RuntimeError(f"init{i} failed")

        async def close():
            calls.append(f"close{i}")

        return init, close

    return tuple(pair(i) for i in range(4))


async def test_every_module_opens_in_order_and_closes_in_reverse(monkeypatch):
    calls = []
    monkeypatch.setattr(container, "_LIFECYCLES", _lifecycles(calls))
    monkeypatch.setattr(container, "get_session_factory", lambda: object())

    async with AsyncExitStack() as stack:
        built = await container.build_container(stack)
        assert calls == ["init0", "init1", "init2", "init3"]

    assert calls[4:] == ["close3", "close2", "close1", "close0"]
    assert isinstance(built.auth, AuthService)
    assert isinstance(built.admin, AdminService)
    assert isinstance(built.chat, ChatService)
    assert isinstance(built.community, CommunityService)
    assert isinstance(built.matching, MatchingService)
    assert isinstance(built.collector, Collector)
    assert isinstance(built.history, HistoryService)
    assert isinstance(built.reservations, ReservationService)
    assert isinstance(built.saves, SavesService)
    assert isinstance(built.streaming, StreamingService)


async def test_a_failing_module_closes_only_those_opened_before_it(monkeypatch):
    calls = []
    monkeypatch.setattr(container, "_LIFECYCLES", _lifecycles(calls, fail_at=2))

    with pytest.raises(RuntimeError, match="init2 failed"):
        async with AsyncExitStack() as stack:
            await container.build_container(stack)

    assert calls == ["init0", "init1", "init2", "close1", "close0"]
