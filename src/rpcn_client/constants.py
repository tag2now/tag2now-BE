# Protocol constants (must match src/server/client.rs and src/server.rs)

HEADER_SIZE      = 15   # bytes
PROTOCOL_VERSION = 30

# PacketType values
PKT_REQUEST    = 0
PKT_REPLY      = 1
PKT_NOTIF      = 2
PKT_SERVERINFO = 3

# CommandType enum values (0-indexed, see src/server/client.rs)
CMD_LOGIN                  = 0
CMD_TERMINATE              = 1
CMD_GET_SERVER_LIST        = 12
CMD_GET_WORLD_LIST         = 13
CMD_SEARCH_ROOM            = 17
CMD_GET_ROOM_EXTERNAL_LIST = 18
CMD_GET_SCORE_RANGE        = 34
CMD_GET_SCORE_FRIENDS      = 35
CMD_GET_SCORE_NPID         = 36
CMD_SEARCH_ROOM_ALL        = 0x0105

# ErrorType::NoError
ERR_NO_ERROR = 0

# comm ID is always 12 ASCII bytes, e.g. b"NPWR04850_00"
COMMUNICATION_ID_SIZE = 12

# Header struct layout: u8 pkt_type | u16 cmd | u32 total_size | u64 packet_id
_HDR_FMT = "<BHIQ"  # 1+2+4+8 = 15 bytes
