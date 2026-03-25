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
from .utils import _format_epoch
from .models import UserInfo, RoomAttr, RoomBinAttr, RoomInfo, SearchRoomsResult, ScoreEntry, ScoreResult
from .helpers import _encode_com_id, _read_cstr, _pack_protobuf, _unpack_data_packet
from .client import RpcnClient

__all__ = [
	"HEADER_SIZE", "PROTOCOL_VERSION",
	"PKT_REQUEST", "PKT_REPLY", "PKT_NOTIF", "PKT_SERVERINFO",
	"Cmd", "ERR_NO_ERROR", "COMMUNICATION_ID_SIZE", "_HDR_FMT",
	"RpcnError",
	"_format_epoch",
	"UserInfo", "RoomAttr", "RoomBinAttr", "RoomInfo", "SearchRoomsResult", "ScoreEntry", "ScoreResult",
	"_encode_com_id", "_read_cstr", "_pack_protobuf", "_unpack_data_packet",
	"RpcnClient",
]
