"""Integration tests for matching service functions against the live RPCN server.

Run with:
    pytest tests/integration/matching/ -v

Protobuf tests (get_rooms, get_leaderboard) require
np2_structs_pb2.py to be generated first:
    python -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto

These tests require a running RPCN server and Redis instance.
The RPCN connection settings are read from shared.settings (env vars).
"""

import asyncio

import pytest
from rpcn_client import SearchRoomsResult
from matching import (
    TTT2_COM_ID,
    get_server_world_tree,
    get_rooms,
    get_leaderboard,
)
from matching.db import init_game_repo, close_game_repo

# ---------------------------------------------------------------------------
# Game-specific constants
# ---------------------------------------------------------------------------

COM_ID = TTT2_COM_ID
BOARD_ID = 4


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _init_repo():
    """Initialize and tear down the game server repository for the module."""
    asyncio.run(init_game_repo())
    yield
    asyncio.run(close_game_repo())


# ---------------------------------------------------------------------------
# Service integration tests
# ---------------------------------------------------------------------------

def test_get_server_world_tree():
    """get_server_world_tree returns dict[str, list[int]]."""
    tree = get_server_world_tree(COM_ID)
    print(f"Returned tree: {tree}")
    assert isinstance(tree, dict)
    for server_id, worlds in tree.items():
        assert isinstance(server_id, str)
        assert isinstance(worlds, list)
        assert all(isinstance(w, int) for w in worlds)


def test_get_rooms():
    """get_rooms returns rooms grouped by type."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    results = get_rooms(COM_ID)
    print(f"Returned rooms: {results}")
    assert isinstance(results, dict)
    for room_type, rooms in results.items():
        assert isinstance(room_type, str)
        assert isinstance(rooms, list)


def test_search_rooms_all(session):
    """search_rooms_all returns all rooms including HIDDEN ones."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    client = session["client"]
    tree = get_server_world_tree(COM_ID)
    all_worlds = [w for worlds in tree.values() for w in worlds]
    for world_id in all_worlds:
        resp = client.search_rooms_all(COM_ID, world_id=world_id)
        print(f"SearchRoomAll world {world_id}: total={resp.total}, rooms={len(resp.rooms)}")
        assert isinstance(resp, SearchRoomsResult)
        assert resp.total >= 0
        for room in resp.rooms:
            assert room.room_id > 0


def test_get_leaderboard():
    """get_leaderboard returns parsed leaderboard dict."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    resp = get_leaderboard(COM_ID, BOARD_ID, 100)
    print(f"Returned leaderboard: {resp}")
    assert isinstance(resp, dict)
