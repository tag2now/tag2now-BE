import ssl
import socket
import struct

from .constants import (
	HEADER_SIZE, PROTOCOL_VERSION,
	PKT_REQUEST, PKT_REPLY, PKT_NOTIF, PKT_SERVERINFO,
	Cmd, ERR_NO_ERROR, _HDR_FMT,
)
from .exceptions import RpcnError
from .models import UserInfo, RoomInfo, SearchRoomsResult, ScoreResult
from .helpers import _encode_com_id, _read_cstr, _pack_protobuf, _unpack_data_packet

try:
	from . import np2_structs_pb2 as pb
except ImportError:
	raise RpcnError(
		"np2_structs_pb2 not found.\n"
		"Generate it with:\n"
		"  python -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto"
	)


class RpcnClient:
	def __init__(self, host: str = "rpcn.rpcs3.net", port: int = 31313):
		self.host = host
		self.port = port
		self._sock = None
		self._packet_id = 0

	# ------------------------------------------------------------------
	# Connection lifecycle
	# ------------------------------------------------------------------

	def connect(self) -> int:
		"""Open a TLS connection and read the server's handshake packet.

		The server immediately sends a 19-byte ServerInfo packet whose 4-byte
		payload is PROTOCOL_VERSION (currently 30).  We verify the version and
		return it.
		"""
		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE  # RPCN uses a self-signed certificate

		raw = socket.create_connection((self.host, self.port), timeout=30)
		self._sock = ctx.wrap_socket(raw, server_hostname=self.host)

		# Read the 15-byte header of the ServerInfo packet
		hdr = self._recv_exact(HEADER_SIZE)
		pkt_type, _cmd, pkt_size, _pkt_id = struct.unpack(_HDR_FMT, hdr)
		if pkt_type != PKT_SERVERINFO:
			raise RpcnError(f"Expected ServerInfo packet (type 3), got {pkt_type}")

		# The payload is PROTOCOL_VERSION as a u32 LE
		payload_size = pkt_size - HEADER_SIZE
		if payload_size < 4:
			raise RpcnError("ServerInfo payload too short")
		payload = self._recv_exact(payload_size)
		(version,) = struct.unpack_from("<I", payload)
		if version != PROTOCOL_VERSION:
			raise RpcnError(f"Protocol version mismatch: server={version}, client={PROTOCOL_VERSION}")
		return version

	def disconnect(self):
		"""Send the Terminate command and close the socket."""
		try:
			self._send(Cmd.TERMINATE, b"")
		except Exception:
			pass
		if self._sock:
			self._sock.close()
			self._sock = None

	def __enter__(self):
		return self

	def __exit__(self, *_):
		self.disconnect()

	# ------------------------------------------------------------------
	# Authentication
	# ------------------------------------------------------------------

	def login(self, username: str, password: str, token: str = "") -> UserInfo:
		"""Log in to RPCN.

		Payload: username\\0 password\\0 token\\0  (token is empty for normal login)

		Returns a LoginInfo with online_name, avatar_url, user_id.
		Raises RpcnError on failure.
		"""
		payload = (
			username.encode("utf-8") + b"\x00"
			+ password.encode("utf-8") + b"\x00"
			+ token.encode("utf-8") + b"\x00"
		)
		self._send(Cmd.LOGIN, payload)
		error, data = self._recv_reply()
		if error != ERR_NO_ERROR:
			names = {
				5: "LoginError",
				6: "LoginAlreadyLoggedIn",
				7: "LoginInvalidUsername",
				8: "LoginInvalidPassword",
				9: "LoginInvalidToken",
			}
			raise RpcnError(f"Login failed: {names.get(error, f'error {error}')}")

		pos = 0
		online_name, pos = _read_cstr(data, pos)
		avatar_url, pos  = _read_cstr(data, pos)
		(user_id,) = struct.unpack_from("<q", data, pos)
		# The remainder is friend-list data which we don't need to parse here.
		return UserInfo(online_name=online_name, avatar_url=avatar_url, user_id=user_id)

	# ------------------------------------------------------------------
	# Server / World list
	# ------------------------------------------------------------------

	def get_server_list(self, com_id: str) -> list:
		"""Return a list of server IDs (u16) for the given comm ID string."""
		data = self._request_with_data(com_id, Cmd.GET_SERVER_LIST)
		(num,) = struct.unpack_from("<H", data, 0)
		return list(struct.unpack_from(f"<{num}H", data, 2))

	def get_world_list(self, com_id: str, server_id: int) -> list:
		"""Return a list of world IDs (u32) for the given comm ID + server."""
		req_data = struct.pack("<H", server_id)
		data = self._request_with_data(com_id, Cmd.GET_WORLD_LIST, req_data)
		(num,) = struct.unpack_from("<I", data, 0)
		return list(struct.unpack_from(f"<{num}I", data, 4))

	# ------------------------------------------------------------------
	# Rooms
	# ------------------------------------------------------------------

	def search_rooms(self, com_id: str, world_id: int = 0, start_index: int = 1, max_results: int = 20, flag_attr: int = 0) -> SearchRoomsResult:
		"""start_index must be >= 1 (the server rejects 0)."""
		req = self._build_search_room_request(world_id, flag_attr, start_index, max_results)
		data = self._request_proto(com_id, Cmd.SEARCH_ROOM, req)

		resp = pb.SearchRoomResponse()
		resp.ParseFromString(_unpack_data_packet(data))
		return SearchRoomsResult(total=resp.total, rooms=[RoomInfo.from_response_room(room) for room in resp.rooms])

	def search_rooms_all(self, com_id: str, world_id: int = 0, start_index: int = 1, max_results: int = 20, flag_attr: int = 0) -> SearchRoomsResult:
		"""Search for all rooms including HIDDEN ones, skipping flag filtering.

		Same request/response format as search_rooms, but the server uses
		is_match_all() which does not exclude HIDDEN rooms or filter by flags.
		"""
		req = self._build_search_room_request(world_id, flag_attr, start_index, max_results)
		data = self._request_proto(com_id, Cmd.SEARCH_ROOM_ALL, req)

		resp = pb.SearchRoomAllResponse()
		resp.ParseFromString(_unpack_data_packet(data))
		return SearchRoomsResult(total=resp.total, rooms=[RoomInfo.from_response_room(room) for room in resp.rooms])

	# ------------------------------------------------------------------
	# Scores / Leaderboards
	# ------------------------------------------------------------------

	def get_score_range(self, com_id: str, board_id: int,
	                    start_rank: int = 1, num_ranks: int = 10,
	                    with_comment: bool = False, with_game_info: bool = False) -> ScoreResult:
		"""Fetch leaderboard entries by rank range.

		Returns a ScoreResult DTO.
		"""
		req = pb.GetScoreRangeRequest()
		req.boardId    = board_id
		req.startRank  = start_rank
		req.numRanks   = num_ranks
		req.withComment  = with_comment
		req.withGameInfo = with_game_info

		data = self._request_proto(com_id, Cmd.GET_SCORE_RANGE, req)

		resp = pb.GetScoreResponse()
		resp.ParseFromString(_unpack_data_packet(data))
		return ScoreResult.from_response(resp)

	def get_score_npid(self, com_id: str, board_id: int, npids: list,
	                   pc_id: int = 0, with_comment: bool = False, with_game_info: bool = False) -> ScoreResult:
		"""Fetch scores for a list of NP IDs.

		Returns a ScoreResult DTO.
		"""
		req = pb.GetScoreNpIdRequest()
		req.boardId    = board_id
		req.withComment  = with_comment
		req.withGameInfo = with_game_info
		for npid in npids:
			entry = req.npids.add()
			entry.npid = npid
			entry.pcId = pc_id

		data = self._request_proto(com_id, Cmd.GET_SCORE_NPID, req)

		resp = pb.GetScoreResponse()
		resp.ParseFromString(_unpack_data_packet(data))
		return ScoreResult.from_response(resp)

	# ------------------------------------------------------------------
	# Internal I/O
	# ------------------------------------------------------------------

	def _build_search_room_request(self, world_id: int, flag_attr: int, start_index: int, max_results: int):
		req = pb.SearchRoomRequest()
		req.worldId = world_id
		req.option = 31
		req.flagAttr = flag_attr
		req.flagFilter = 0
		for i in [0x4C, 0x4D, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53]:
			at_id = req.attrId.add()
			at_id.value = i
		req.rangeFilter_startIndex = max(1, start_index)
		req.rangeFilter_max = min(max_results, 20)
		return req

	def _request_proto(self, com_id: str, cmd: Cmd, req) -> bytes:
		req_data = _pack_protobuf(req)
		return self._request_with_data(com_id, cmd, req_data)

	def _request_with_data(self, com_id: str, cmd: Cmd, req_data=None) -> bytes:
		payload = _encode_com_id(com_id)
		if req_data is not None:
			payload += req_data

		self._send(cmd, payload)
		error, data = self._recv_reply()
		if error != ERR_NO_ERROR:
			raise RpcnError(f"{cmd.label} error {error}")
		return data

	def _send(self, cmd: int, payload: bytes):
		self._packet_id += 1
		total_size = HEADER_SIZE + len(payload)
		header = struct.pack(_HDR_FMT, PKT_REQUEST, cmd, total_size, self._packet_id)
		self._sock.sendall(header + payload)

	def _recv_exact(self, n: int) -> bytes:
		buf = bytearray()
		while len(buf) < n:
			chunk = self._sock.recv(n - len(buf))
			if not chunk:
				raise RpcnError("Connection closed unexpectedly by server")
			buf.extend(chunk)
		return bytes(buf)

	def _recv_reply(self) -> tuple[int, bytes]:
		"""Read packets until a Reply is found, discarding notifications."""
		while True:
			hdr = self._recv_exact(HEADER_SIZE)
			pkt_type, cmd, pkt_size, _pkt_id = struct.unpack(_HDR_FMT, hdr)

			payload_size = pkt_size - HEADER_SIZE
			payload = self._recv_exact(payload_size) if payload_size > 0 else b""

			if pkt_type == PKT_NOTIF:
				continue

			if pkt_type != PKT_REPLY:
				raise RpcnError(f"Unexpected packet type {pkt_type} (expected Reply=1)")

			error_type = payload[0] if payload else 0
			data = payload[1:] if len(payload) > 1 else b""
			return error_type, data