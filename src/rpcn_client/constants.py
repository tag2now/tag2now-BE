# Protocol constants (must match src/server/client.rs and src/server.rs)

from enum import IntEnum

HEADER_SIZE      = 15   # bytes
PROTOCOL_VERSION = 30

# PacketType values
PKT_REQUEST    = 0
PKT_REPLY      = 1
PKT_NOTIF      = 2
PKT_SERVERINFO = 3


class Cmd(IntEnum):
	LOGIN                  = 0
	TERMINATE              = 1
	GET_SERVER_LIST        = 12
	GET_WORLD_LIST         = 13
	SEARCH_ROOM            = 17
	GET_ROOM_EXTERNAL_LIST = 18
	GET_SCORE_RANGE        = 34
	GET_SCORE_FRIENDS      = 35
	GET_SCORE_NPID         = 36
	SEARCH_ROOM_ALL        = 0x0105

	@property
	def label(self) -> str:
		return self.name.replace("_", " ").title().replace(" ", "")


# ErrorType::NoError
ERR_NO_ERROR = 0

# comm ID is always 12 ASCII bytes, e.g. b"NPWR04850_00"
COMMUNICATION_ID_SIZE = 12

# Header struct layout: u8 pkt_type | u16 cmd | u32 total_size | u64 packet_id
_HDR_FMT = "<BHIQ"  # 1+2+4+8 = 15 bytes
