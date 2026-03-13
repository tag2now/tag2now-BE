import struct
from .constants import COMMUNICATION_ID_SIZE
from .exceptions import RpcnError
from .models import ScoreEntry, ScoreResult


def _encode_com_id(com_id_str: str) -> bytes:
	"""Encode a comm ID string like 'NPWR04850_00' to 12 ASCII bytes."""
	if len(com_id_str) != COMMUNICATION_ID_SIZE:
		raise ValueError(f"comm ID must be exactly {COMMUNICATION_ID_SIZE} chars, got {len(com_id_str)!r}")
	return com_id_str.encode("ascii")


def _read_cstr(data: bytes, pos: int) -> tuple:
	"""Read a null-terminated UTF-8 string starting at *pos* in *data*.

	Returns (string, new_pos).
	"""
	end = data.index(b"\x00", pos)
	return data[pos:end].decode("utf-8", errors="replace"), end + 1


def _pack_protobuf(msg) -> bytes:
	"""Serialize *msg* with a u32 LE length prefix (matches get_protobuf in stream_extractor.rs)."""
	raw = msg.SerializeToString()
	return struct.pack("<I", len(raw)) + raw


def _unpack_data_packet(data: bytes) -> bytes:
	"""Extract the raw protobuf bytes written by Client::add_data_packet.

	add_data_packet prepends a u32 LE length before the protobuf bytes.
	"""
	if len(data) < 4:
		raise RpcnError(f"Data packet too short: {len(data)} bytes")
	(size,) = struct.unpack_from("<I", data, 0)
	return data[4:4 + size]


def _score_response_to_dto(resp) -> ScoreResult:
	"""Convert a GetScoreResponse protobuf into a ScoreResult DTO."""
	entries = []
	for i, entry in enumerate(resp.rankArray):
		comment = resp.commentArray[i] if i < len(resp.commentArray) else ""
		game_info = resp.infoArray[i].data if i < len(resp.infoArray) else b""
		entries.append(ScoreEntry(
			rank=entry.rank,
			np_id=entry.npId,
			online_name=entry.onlineName,
			score=entry.score,
			pc_id=entry.pcId,
			record_date=entry.recordDate,
			has_game_data=entry.hasGameData,
			comment=comment,
			game_info=game_info,
		))
	return ScoreResult(
		total_records=resp.totalRecord,
		last_sort_date=resp.lastSortDate,
		entries=entries,
	)


def _import_pb2():
	"""Import the generated protobuf module, with a helpful error if missing."""
	try:
		from . import np2_structs_pb2 as pb
		return pb
	except ImportError:
		raise RpcnError(
			"np2_structs_pb2 not found.\n"
			"Generate it with:\n"
			"  python -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto"
		)
