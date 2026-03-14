"""Tekken Tag Tournament 2 RPCN queries and API server.

Credentials are read from environment variables (or a .env file):
  RPCN_USER      - RPCN username (required)
  RPCN_PASSWORD  - RPCN password (required)
  RPCN_TOKEN     - RPCN token   (optional, default: "")
  RPCN_HOST      - server host  (optional, default: np.rpcs3.net)
  RPCN_PORT      - server port  (optional, default: 31313)

API usage:
  RPCN_USER=you RPCN_PASSWORD=secret uvicorn tekken_tt2.app:app --reload
"""

import json
import logging
from contextlib import contextmanager

import redis as _redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from rpcn_client import RpcnClient, RpcnError
from tekken_tt2.models import TTT2_COM_ID, TTT2_BOARD_ID
from tekken_tt2.service import get_server_world_tree, get_rooms, get_leaderboard
from tekken_tt2.settings import get_settings


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_get(key: str):
	settings = get_settings()
	try:
		client = _redis.from_url(settings.redis_url, decode_responses=True)
		raw = client.get(key)
		return json.loads(raw) if raw else None
	except Exception as e:
		logging.warning("Redis get failed: %s", e)
		return None


def _cache_set(key: str, value, ttl: int):
	settings = get_settings()
	try:
		client = _redis.from_url(settings.redis_url, decode_responses=True)
		client.setex(key, ttl, json.dumps(value))
	except Exception as e:
		logging.warning("Redis set failed: %s", e)


@contextmanager
def _api_client():
	"""Open an authenticated RpcnClient for an API request."""
	settings = get_settings()
	with RpcnClient(host=settings.rpcn_host, port=settings.rpcn_port) as client:
		try:
			client.connect()
			client.login(settings.rpcn_user, settings.rpcn_password, settings.rpcn_token)
			yield client
		except RpcnError as exc:
			raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

app = FastAPI(
	title="Tekken Tag Tournament 2 RPCN API",
	description="Live data from the RPCN multiplayer server for TTT2.",
)

app.add_middleware(
	CORSMiddleware,
	allow_origins=get_settings().cors_origins,
	allow_methods=["*"],
	allow_headers=["*"],
)


@app.get("/servers", summary="Server and world list")
def servers():
	"""Return the server → world hierarchy."""
	key = f"ttt2:servers:{TTT2_COM_ID}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		tree = get_server_world_tree(client, TTT2_COM_ID)
	result = {str(k): v for k, v in tree.items()}
	_cache_set(key, result, get_settings().cache_ttl_servers)
	return result


@app.get("/rooms", summary="Active rooms")
def rooms():
	"""Return all active rooms across every world."""
	key = f"ttt2:rooms:{TTT2_COM_ID}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		tree = get_server_world_tree(client, TTT2_COM_ID)
		all_worlds = [w for worlds in tree.values() for w in worlds]
		room_map = get_rooms(client, TTT2_COM_ID, all_worlds)
	result = {str(world_id): resp for world_id, resp in room_map.items()}
	_cache_set(key, jsonable_encoder(result), get_settings().cache_ttl_rooms)
	return result


@app.get("/rooms/all", summary="All rooms including hidden")
def rooms_all():
	"""Search all rooms including hidden ones via SearchRoomAll."""
	key = f"ttt2:rooms_all:{TTT2_COM_ID}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		resp = client.search_rooms_all(TTT2_COM_ID)
	_cache_set(key, jsonable_encoder(resp), get_settings().cache_ttl_rooms_all)
	return resp


@app.get("/leaderboard", summary="Leaderboard entries")
def leaderboard(
	board: int = Query(default=TTT2_BOARD_ID, description="Score board ID"),
	top: int = Query(default=10, ge=1, le=100, description="Number of entries to return"),
):
	"""Return the top N leaderboard entries with TTT2 character info decoded."""
	key = f"ttt2:leaderboard:{TTT2_COM_ID}:{board}:{top}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		lb = get_leaderboard(client, TTT2_COM_ID, board, num_ranks=top)
	_cache_set(key, jsonable_encoder(lb), get_settings().cache_ttl_leaderboard)
	return lb
