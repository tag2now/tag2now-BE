"""RPCN adapter for the GameServerPort."""

import struct

from rpcn_client import RpcnError
from matching.models import (
    CharInfo,
    Rank,
    RoomInfoDTO,
    TTT2GameInfo,
    TTT2LeaderboardEntry,
    TTT2LeaderboardResult,
    _GAME_INFO_FMT,
    _GAME_INFO_SIZE,
)
from matching.ports import GameServerPort
from matching.rpcn_lifecycle import api_client, shutdown_client


class RpcnGameServerAdapter(GameServerPort):
    """GameServerPort backed by the RPCN binary protocol."""

    async def init(self) -> None:
        pass  # lazy connection via api_client()

    async def close(self) -> None:
        shutdown_client()

    def get_server_world_tree(self, com_id: str) -> dict[int, list[int]]:
        with api_client() as client:
            servers = client.get_server_list(com_id)
            tree = {}
            for server_id in servers:
                tree[server_id] = client.get_world_list(com_id, server_id)
            return tree

    def search_rooms(self, com_id: str, worlds: list[int]) -> list[RoomInfoDTO]:
        with api_client() as client:
            all_rooms: list[RoomInfoDTO] = []
            for world_id in worlds:
                try:
                    resp = client.search_rooms(com_id, world_id=world_id, max_results=20)
                    if resp.total > 0:
                        all_rooms.extend(RoomInfoDTO(room) for room in resp.rooms)
                except RpcnError:
                    pass
            return all_rooms

    def search_rooms_all(self, com_id: str, worlds: list[int]) -> list[RoomInfoDTO]:
        with api_client() as client:
            all_rooms: list[RoomInfoDTO] = []
            for world_id in worlds:
                try:
                    resp = client.search_rooms_all(com_id, world_id=world_id)
                    if resp.total > 0:
                        all_rooms.extend(RoomInfoDTO(room) for room in resp.rooms)
                except RpcnError:
                    pass
            return all_rooms

    def get_leaderboard(self, com_id: str, board_id: int, num_ranks: int) -> TTT2LeaderboardResult:
        with api_client() as client:
            result = client.get_score_range(
                com_id, board_id,
                start_rank=1, num_ranks=num_ranks,
                with_comment=True, with_game_info=True,
            )
        entries = [
            TTT2LeaderboardEntry(
                rank=e.rank, np_id=e.np_id, online_name=e.online_name,
                score=e.score, pc_id=e.pc_id, record_date=e.record_date,
                has_game_data=e.has_game_data, comment=e.comment,
                player_info=_parse_game_info(e.game_info) if e.game_info else None,
            )
            for e in result.entries
        ]
        return TTT2LeaderboardResult(
            total_records=result.total_records,
            last_sort_date=result.last_sort_date,
            entries=entries,
        )


def _parse_game_info(data: bytes) -> TTT2GameInfo | None:
    """Parse a TTT2 game_info blob. Returns None if data is too short."""
    if len(data) < _GAME_INFO_SIZE:
        return None
    c1_id, c2_id, c1_rank, c2_rank, c1_w, c2_w, c1_l, c2_l = struct.unpack(
        _GAME_INFO_FMT, data[:_GAME_INFO_SIZE]
    )
    return TTT2GameInfo(
        main_char_info=CharInfo(char_id=c1_id, rank_info=Rank(id=c1_rank), wins=c1_w, losses=c1_l),
        sub_char_info=CharInfo(char_id=c2_id, rank_info=Rank(id=c2_rank), wins=c2_w, losses=c2_l),
    )
