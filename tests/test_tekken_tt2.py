"""Integration tests for tekken_tt2.py query functions against the live RPCN server.

Run with:
    pytest test_tekken_tt2.py -v

Protobuf tests (get_rooms, get_leaderboard) require
np2_structs_pb2.py to be generated first:
    python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
"""

import pytest
from rpcn_client import SearchRoomsResult
from matching import (
    TTT2_COM_ID,
    TTT2LeaderboardResult,
    TTT2LeaderboardEntry,
    get_server_world_tree,
    get_rooms,
    get_leaderboard,
)

# ---------------------------------------------------------------------------
# Game-specific constants
# ---------------------------------------------------------------------------

COM_ID   = TTT2_COM_ID
BOARD_ID = 0


# ---------------------------------------------------------------------------
# tekken_tt2.py wrapper tests
# ---------------------------------------------------------------------------

def test_get_server_world_tree(session):
    """Integration test for get_server_world_tree — returns dict[int, list[int]]."""
    client = session["client"]
    tree = get_server_world_tree(client, COM_ID)
    print(f"Returned tree: {tree}")
    assert isinstance(tree, dict)
    for server_id, worlds in tree.items():
        assert isinstance(server_id, int)
        assert isinstance(worlds, list)
        assert all(isinstance(w, int) for w in worlds)


def test_get_rooms(session):
    """Integration test for get_rooms — returns rooms grouped by type."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    client = session["client"]
    tree = get_server_world_tree(client, COM_ID)
    all_worlds = [w for worlds in tree.values() for w in worlds]
    results = get_rooms(client, COM_ID, all_worlds)
    print(f"Returned rooms: {results}")
    assert isinstance(results, dict)
    for room_type, rooms in results.items():
        assert isinstance(room_type, str)
        assert isinstance(rooms, list)


def test_search_rooms_all(session):
    """Integration test for search_rooms_all — returns all rooms including HIDDEN ones."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    client = session["client"]
    tree = get_server_world_tree(client, COM_ID)
    all_worlds = [w for worlds in tree.values() for w in worlds]
    for world_id in all_worlds:
        resp = client.search_rooms_all(COM_ID, world_id=world_id)
        print(f"SearchRoomAll world {world_id}: total={resp.total}, rooms={len(resp.rooms)}")
        assert isinstance(resp, SearchRoomsResult)
        assert resp.total >= 0
        for room in resp.rooms:
            assert room.room_id > 0


def test_get_leaderboard(session):
    """Integration test for get_leaderboard — returns TTT2LeaderboardResult with parsed entries."""
    pytest.importorskip("rpcn_client.np2_structs_pb2")
    client = session["client"]
    # resp = get_leaderboard(client, COM_ID, BOARD_ID, num_ranks=100)
    resp = get_leaderboard(client, COM_ID, 4, num_ranks=100)
    print(f"Returned leaderboard: {resp}")
    map = [{
        'id': ent.np_id,
       'main': ent.player_info.main_char_info.__str__(),
        'sub': ent.player_info.sub_char_info.__str__(),
    } for ent in resp.entries]
    assert isinstance(resp, TTT2LeaderboardResult)
    for entry in resp.entries:
        assert isinstance(entry, TTT2LeaderboardEntry)
        assert isinstance(entry.rank, int)
        assert isinstance(entry.np_id, str)


