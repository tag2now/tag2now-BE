"""RPCN client — minimal Python client for the RPCN PSN multiplayer server.

Protocol reference derived from: https://github.com/RPCS3/rpcn
"""

from .constants import (
	HEADER_SIZE,
	PROTOCOL_VERSION,
	PKT_REQUEST,
	PKT_REPLY,
	PKT_NOTIF,
	PKT_SERVERINFO,
	Cmd,
	ERR_NO_ERROR,
	COMMUNICATION_ID_SIZE,
	_HDR_FMT,
)
from .exceptions import RpcnError
from .models import UserInfo, RoomAttr, RoomBinAttr, RoomInfo, SearchRoomsResult, ScoreEntry, ScoreResult
from .client import RpcnClient

__all__ = [
	"HEADER_SIZE", "PROTOCOL_VERSION",
	"PKT_REQUEST", "PKT_REPLY", "PKT_NOTIF", "PKT_SERVERINFO",
	"Cmd", "ERR_NO_ERROR", "COMMUNICATION_ID_SIZE", "_HDR_FMT",
	"RpcnError",
	"UserInfo", "RoomAttr", "RoomBinAttr", "RoomInfo", "SearchRoomsResult", "ScoreEntry", "ScoreResult",
	"RpcnClient",
]
