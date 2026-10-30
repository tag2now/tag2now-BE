"""Integration tests for matching service functions against the live RPCN server.

Run with:
    pytest tests/integration/matching/ -v

Protobuf tests (get_rooms, get_leaderboard) require
np2_structs_pb2.py to be generated first:
    python -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto

These tests require a running RPCN server and Redis instance.
The RPCN connection settings are read from shared.settings (env vars).
"""

from functools import partial

import pytest
from rpcn_client import SearchRoomsResult
from matching.adapters.rpcn import RpcnGameServerAdapter
from matching.rpcn_lifecycle import SharedRpcnClient, create_client
from matching.service import MatchingService
from shared.settings import get_settings
from shared.ttt2 import TTT2_COM_ID, TTT2_RANK_BOARD_ID

# These log in to RPCN, so they carry the same one-session-per-account
# restriction as tests/integration/test_rpcn_client.py.
pytestmark = pytest.mark.rpcn

# ---------------------------------------------------------------------------
# Game-specific constants
# ---------------------------------------------------------------------------

COM_ID = TTT2_COM_ID
BOARD_ID = TTT2_RANK_BOARD_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rpcn():
    """One RPCN connection for the module, disconnected after it."""
    s = get_settings()
    shared = SharedRpcnClient(
        partial(
            create_client,
            s.rpcn_host,
            s.rpcn_port,
            s.rpcn_user,
            s.rpcn_password,
            s.rpcn_token,
            s.rpcn_metric_enable,
        )
    )
    yield shared
    shared.shutdown()


@pytest.fixture(scope="module")
def service(rpcn):
    return MatchingService(RpcnGameServerAdapter(rpcn))


# ---------------------------------------------------------------------------
# Service integration tests
# ---------------------------------------------------------------------------


def test_get_server_world_tree(service):
    """get_server_world_tree returns dict[str, list[int]]."""
    tree = service.get_server_world_tree(COM_ID)
    print(f"Returned tree: {tree}")
    assert isinstance(tree, dict)
    for server_id, worlds in tree.items():
        assert isinstance(server_id, str)
        assert isinstance(worlds, list)
        assert all(isinstance(w, int) for w in worlds)


def test_search_rooms_all(service, rpcn):
    """search_rooms_all returns all rooms including HIDDEN ones."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    tree = service.get_server_world_tree(COM_ID)
    all_worlds = [w for worlds in tree.values() for w in worlds]
    with rpcn.api_client() as client:
        for world_id in all_worlds:
            resp = client.search_rooms_all(COM_ID, world_id=world_id)
            print(f"SearchRoomAll world {world_id}: total={resp.total}, rooms={len(resp.rooms)}")
            assert isinstance(resp, SearchRoomsResult)
            assert resp.total >= 0
            for room in resp.rooms:
                assert room.room_id > 0


def test_get_leaderboard(service):
    """get_leaderboard returns parsed leaderboard dict."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    resp = service.get_leaderboard(COM_ID, BOARD_ID, 200)
    print(f"Returned leaderboard: {resp}")
    assert isinstance(resp, dict)
