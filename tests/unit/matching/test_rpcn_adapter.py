"""The RPCN adapter turns RPCN's rooms into matching's own."""

from contextlib import contextmanager

from matching.adapters.rpcn import RpcnGameServerAdapter
from matching.models import Rank, RoomType, RoomUser
from rpcn_client import RoomAttr, RoomInfo, RpcnError, SearchRoomsResult, UserInfo

COM_ID = "NPWR02973_00"


def _listed(room_id, *npids, rank_code):
    """A room as RPCN answers it; TTT2 keeps the rank code in int attribute 4."""
    return RoomInfo(
        room_id=room_id,
        owner_npid=npids[0],
        owner_online_name=npids[0].title(),
        current_members=len(npids),
        max_slots=2,
        flag_attr=0,
        int_attrs=[RoomAttr(id=i, value=rank_code if i == 4 else 0) for i in range(8)],
        bin_search_attrs=[],
        bin_attrs=[],
        users=[UserInfo(online_name=npid.title(), avatar_url=f"{npid}.png", npid=npid) for npid in npids],
    )


class FakeClient:
    def __init__(self, worlds):
        self._worlds = worlds

    def search_rooms_all(self, com_id, world_id):
        rooms = self._worlds[world_id]
        if isinstance(rooms, Exception):
            raise rooms
        return SearchRoomsResult(total=len(rooms), rooms=rooms)


class FakeRpcn:
    def __init__(self, worlds):
        self._client = FakeClient(worlds)

    @contextmanager
    def api_client(self):
        yield self._client


def _adapter(**worlds):
    return RpcnGameServerAdapter(FakeRpcn({int(w.removeprefix("w")): rooms for w, rooms in worlds.items()}))


def test_a_rank_code_of_zero_is_a_player_match_with_no_rank():
    [room] = _adapter(w1=[_listed(7, "alice", rank_code=0)]).search_rooms_all(COM_ID, [1])

    assert (room.room_type, room.rank_info) == (RoomType.PLAYER_MATCH, None)


def test_any_other_rank_code_is_a_rank_match_at_that_rank():
    [room] = _adapter(w1=[_listed(7, "alice", rank_code=10)]).search_rooms_all(COM_ID, [1])

    assert (room.room_type, room.rank_info) == (RoomType.RANK_MATCH, Rank(id=10))


def test_a_room_keeps_its_owner_size_and_members():
    [room] = _adapter(w1=[_listed(7, "alice", "bob", rank_code=10)]).search_rooms_all(COM_ID, [1])

    assert (room.room_id, room.owner_npid, room.owner_online_name) == (7, "alice", "Alice")
    assert (room.current_members, room.max_slots) == (2, 2)
    assert room.users == [RoomUser("Alice", "alice.png", "alice"), RoomUser("Bob", "bob.png", "bob")]


def test_a_world_that_fails_leaves_the_other_worlds_rooms():
    rooms = _adapter(w1=RpcnError("world down"), w2=[_listed(8, "carol", rank_code=0)]).search_rooms_all(COM_ID, [1, 2])

    assert [room.room_id for room in rooms] == [8]
