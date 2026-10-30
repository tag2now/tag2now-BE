"""The composition root opens resources in order and closes them in reverse."""

from contextlib import AsyncExitStack, asynccontextmanager

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


@pytest.fixture
def closed(monkeypatch):
    """The name of each resource, in the order it was closed. The database is faked;
    the others close for real, so the test leaves no client open."""
    names = []

    @asynccontextmanager
    async def open_database():
        try:
            yield object()
        finally:
            names.append("database")

    monkeypatch.setattr(container, "open_database", open_database)
    for cls, name in [
        (container.RpcnApiClient, "rpcn_api"),
        (container.SaveAdminServer, "save_admin"),
        (container.ChzzkPlatform, "chzzk"),
        (container.RpcnGameServerAdapter, "game_server"),
    ]:
        monkeypatch.setattr(cls, "close", _recording(cls.close, name, names))
    return names


def _recording(close, name, names):
    async def recorded(self):
        names.append(name)
        await close(self)

    return recorded


async def test_every_service_is_built_and_resources_close_in_reverse(closed):
    async with AsyncExitStack() as stack:
        built = await container.build_container(stack)
        assert closed == []

    assert closed == ["game_server", "chzzk", "save_admin", "rpcn_api", "database"]
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


async def test_a_failure_part_way_closes_only_what_was_opened_before_it(closed, monkeypatch):
    async def fail(self):
        raise RuntimeError("save-admin failed")

    monkeypatch.setattr(container.SaveAdminServer, "init", fail)

    with pytest.raises(RuntimeError, match="save-admin failed"):
        async with AsyncExitStack() as stack:
            await container.build_container(stack)

    assert closed == ["rpcn_api", "database"]
