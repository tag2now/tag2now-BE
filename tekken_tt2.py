"""Tekken Tag Tournament 2 RPCN queries.

Queries the official RPCN server for TTT2 server/world list, active rooms,
and leaderboard scores.

Usage:
  pip install -r requirements.txt
  python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
  python tekken_tt2.py --user YOUR_USER --password YOUR_PASS

Comm ID note:
  NPWR04850_00 is the candidate for Tekken Tag Tournament 2 (NPEB01406 / NPUB30958).
  If get_server_list() returns an empty list, the comm ID is wrong for your
  region — try the alternate below.  The definitive source is the game's
  PARAM.SFO (NP_COMMUNICATION_ID field) or RPCS3's gamedb.yml.
"""

import argparse
import struct
from dataclasses import dataclass
from rpcn_client import RpcnClient, RpcnError, SearchRoomsResult, ScoreEntry
from tekken_tt2_data import TTT2_CHARACTERS

# ---------------------------------------------------------------------------
# Game constants
# ---------------------------------------------------------------------------

# Primary comm ID (EU/US disc — verify against your game's PARAM.SFO)
TTT2_COM_ID = "NPWR02973_00"

# Score board IDs — TTT2 uses board 0 for the main ranking
TTT2_BOARD_ID = 0

# game_info struct: 4 header bytes + 4 big-endian uint32s + 44 bytes padding
_GAME_INFO_FMT = ">4B4I"
_GAME_INFO_SIZE = 20  # first 20 bytes are meaningful


@dataclass
class CharInfo:
	"""A single character's stats from a TTT2 leaderboard entry."""
	char_id: int
	rank: int
	wins: int
	losses: int

	@property
	def name(self) -> str:
		return TTT2_CHARACTERS.get(self.char_id, f"Unknown(0x{self.char_id:02x})")

	def __str__(self):
		return f"{self.name}/{hex(self.char_id)}(rank {self.rank}) {self.wins}W/{self.losses}L"


@dataclass
class TTT2GameInfo:
	"""Parsed TTT2 game_info from a 64-byte leaderboard blob."""
	main_char_info: CharInfo
	sub_char_info: CharInfo

	def __str__(self):
		return f"{self.main_char_info} + {self.sub_char_info}"


def parse_game_info(data: bytes) -> TTT2GameInfo | None:
	"""Parse a 64-byte TTT2 game_info blob. Returns None if data is too short."""
	if len(data) < _GAME_INFO_SIZE:
		return None
	c1_id, c2_id, c1_rank,c2_rank, c1_w, c2_w, c1_l, c2_l = struct.unpack(
		_GAME_INFO_FMT, data[:_GAME_INFO_SIZE]
	)
	return TTT2GameInfo(
		main_char_info=CharInfo(char_id=c1_id, rank=c1_rank, wins=c1_w, losses=c1_l),
		sub_char_info=CharInfo(char_id=c2_id, rank=c2_rank, wins=c2_w, losses=c2_l),
	)


@dataclass
class TTT2LeaderboardEntry:
	"""A leaderboard entry with game_info already parsed into TTT2GameInfo."""
	rank: int
	np_id: str
	online_name: str
	score: int
	pc_id: int
	record_date: int
	has_game_data: bool
	comment: str
	player_info: TTT2GameInfo | None

	def __str__(self):
		base = f"#{self.rank} {self.online_name} ({self.np_id}) score={self.score}"
		if self.player_info:
			base += f"\n       >> {self.player_info}"
		return base


@dataclass
class TTT2LeaderboardResult:
	"""Leaderboard result with parsed TTT2-specific entries."""
	total_records: int
	last_sort_date: int
	entries: list[TTT2LeaderboardEntry]


def format_score_entry(entry: ScoreEntry) -> str:
	"""Format a ScoreEntry with TTT2-specific game_info decoding."""
	base = str(entry)
	if entry.game_info:
		info = parse_game_info(entry.game_info)
		if info:
			base += f"\n       >> {info}"
	return base


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def get_server_world_tree(client: RpcnClient, com_id: str) -> dict[int, list[int]]:
	"""Fetch the server → world hierarchy.  Returns {server_id: [world_ids]}."""
	servers = client.get_server_list(com_id)
	tree = {}
	for server_id in servers:
		tree[server_id] = client.get_world_list(com_id, server_id)
	return tree


def get_rooms(client: RpcnClient, com_id: str, worlds: list[int]) -> dict[int, SearchRoomsResult]:
	"""Search active rooms across all worlds.  Returns {world_id: result}, skipping empty/failed."""
	results = {}
	for world_id in worlds:
		try:
			resp = client.search_rooms(com_id, world_id=world_id, max_results=20)
			if resp.total > 0:
				results[world_id] = resp
		except RpcnError:
			pass
	return results


def get_leaderboard(client: RpcnClient, com_id: str, board_id: int, num_ranks: int = 10) -> TTT2LeaderboardResult:
	"""Fetch the top N leaderboard entries with parsed TTT2 game_info."""
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
			player_info=parse_game_info(e.game_info) if e.game_info else None,
		)
		for e in result.entries
	]
	return TTT2LeaderboardResult(
		total_records=result.total_records,
		last_sort_date=result.last_sort_date,
		entries=entries,
	)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
	parser = argparse.ArgumentParser(description="Tekken Tag Tournament 2 RPCN queries")
	parser.add_argument("--host",     default="np.rpcs3.net")
	parser.add_argument("--port",     type=int, default=31313)
	parser.add_argument("--user",     required=True, default="lsjin",help="RPCN username")
	parser.add_argument("--password", required=True, default="crecent1",help="RPCN password")
	parser.add_argument("--token",    default="63FE49A5083ECBA0", help="RPCN token (optional)")
	parser.add_argument("--com-id",   default=TTT2_COM_ID,
	                    help=f"Comm ID to query (default: {TTT2_COM_ID})")
	parser.add_argument("--board",    type=int, default=TTT2_BOARD_ID,
	                    help=f"Score board ID (default: {TTT2_BOARD_ID})")
	parser.add_argument("--top",      type=int, default=10,
	                    help="Number of leaderboard entries to display (default: 10)")
	args = parser.parse_args()

	with RpcnClient(host=args.host, port=args.port) as client:
		print(f"Connecting to {args.host}:{args.port} ...")
		version = client.connect()
		print(f"  Protocol version: {version}")

		print(f"Logging in as {args.user!r} ...")
		info = client.login(args.user, args.password, args.token)
		print(f"  Logged in — {info}")

		# Server → world tree
		tree = get_server_world_tree(client, args.com_id)
		print(f"\n=== Server list for {args.com_id} ({len(tree)} server(s)) ===")
		all_worlds = []
		for server_id, worlds in tree.items():
			print(f"  Server {server_id}: {len(worlds)} world(s) -> {worlds}")
			all_worlds.extend(worlds)

		# Active rooms
		print(f"\n=== Active rooms for {args.com_id} ===")
		rooms = get_rooms(client, args.com_id, all_worlds)
		for world_id, resp in rooms.items():
			print(f"\n  World {world_id}: {resp.total} room(s) (showing {len(resp.rooms)})")
			for room in resp.rooms:
				print(f"    {room}")
		if not rooms:
			print("  (no active rooms found)")

		# Leaderboard
		print(f"\n=== Top {args.top} leaderboard (board {args.board}) for {args.com_id} ===")
		try:
			lb = get_leaderboard(client, args.com_id, args.board, num_ranks=args.top)
			if lb.total_records == 0:
				print("  (no scores recorded)")
			else:
				print(f"  Total records: {lb.total_records}")
				for entry in lb.entries:
					for line in str(entry).splitlines():
						print(f"  {line}")
		except RpcnError as e:
			print(f"  Leaderboard query failed — {e}")

	print("\nDone.")


if __name__ == "__main__":
	main()
