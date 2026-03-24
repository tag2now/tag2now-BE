import struct
from .constants import COMMUNICATION_ID_SIZE
from .exceptions import RpcnError


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
