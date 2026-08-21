# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Backend for **tag2now** — a live info dashboard for Tekken Tag Tournament 2 (TTT2). A FastAPI server that pulls live data from [RPCN](https://github.com/RPCS3/rpcn) (the PSN-compatible multiplayer server used by the RPCS3 emulator), serves it to the frontend, and persists history for statistics. It also hosts a community board.

The frontend lives in a sibling repository, `tag2now-FE`.

## Setup

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto
```

The last command generates `src/rpcn_client/np2_structs_pb2.py` (not committed). It is required by `search_rooms`, `get_score_range`, and `get_score_npid`, and must be regenerated whenever `np2_structs.proto` changes.

## Python environment

Always use the project virtual environment when running Python commands:

```bash
.venv/Scripts/python.exe -m pytest ...
.venv/Scripts/python.exe -m rpcn_client ...
.venv/Scripts/python.exe -m grpc_tools.protoc ...
```

## Running

The ASGI app is `src/app.py:app`. Note `--app-dir src`, since packages live under `src/`.

```bash
# Dev server with reload
.venv/Scripts/python.exe -m uvicorn app:app --reload --app-dir src

# Dependencies (Redis, PostgreSQL, DynamoDB Local) + both images
docker compose up

# RPCN client CLI smoke test (connect + login + disconnect)
.venv/Scripts/python.exe -m rpcn_client --user YOUR_USER --password YOUR_PASS
```

Redis is a hard dependency: `app.py` runs `redis_health_check()` at import time and calls `os._exit(1)` if Redis is unreachable.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/unit/ -v          # no external services needed
docker compose -f compose.test.yml up -d --wait            # Redis + PostgreSQL
.venv/Scripts/python.exe -m pytest tests/integration/ -v   # needs services + RPCN credentials
```

- `tests/unit/` — pure logic; no network, no database.
- `tests/integration/` — requires Redis and PostgreSQL from `compose.test.yml`. `tests/integration/test_rpcn_client.py` additionally hits the live RPCN server and needs valid `RPCN_*` credentials.

`pyproject.toml` sets `pythonpath = ["src"]` and `asyncio_mode = "auto"`, so async tests need no `@pytest.mark.asyncio` decorator.

## Configuration

`shared/settings.py` defines a pydantic-settings `Settings` model loaded from `env/.env` plus `env/.env.{profile}`, where profile comes from the `FAST_API_PROFILE` environment variable (default `local`). `get_settings()` is `@lru_cache`d — settings are read once per process.

Profiles present: `local`, `dev`, `prod` (plus `.env.example` as the template).

Required with no default: `rpcn_user`, `rpcn_password`, `rpcn_token`, `redis_url`.

Cache TTLs are settings, not constants — `cache_ttl_servers`, `cache_ttl_leaderboard`, `cache_ttl_rooms`, `cache_ttl_rooms_all`, `cache_ttl_community`, `cache_ttl_activity`, `cache_ttl_player_hours`, `matchmaking_ttl`.

## Architecture

Four domain modules under `src/`, plus a `shared/` layer and the standalone `rpcn_client` package.

| Module | Responsibility |
|--------|----------------|
| `matching/` | Live rooms, leaderboard, player lookup, matchmaking detection |
| `history/` | Persisted snapshots and time-series statistics |
| `community/` | Message board — posts, comments, thumbs |
| `shared/` | Settings, Redis cache, database, event bus, exceptions |
| `rpcn_client/` | Standalone RPCN protocol client (no FastAPI dependency) |

### Hexagonal layering

**Follow this pattern when adding a module.** Each domain module uses the same file layout:

| File | Role |
|------|------|
| `ports.py` | Abstract repository interface (`ABC` with `@abstractmethod`) |
| `adapters/` | Concrete implementations of the port (PostgreSQL, DynamoDB, RPCN) |
| `db.py` | Repository factory + lifecycle — module-level `_repo`, `init_*`, `close_*`, `get_*` |
| `service.py` | Application service — orchestrates ports, caching, and domain logic |
| `router.py` | FastAPI `APIRouter`; delegates to `service`, holds no business logic |
| `models.py` | Pydantic request/response models and domain DTOs |
| `exceptions.py` | Domain-specific exceptions |

Routers depend on services; services depend on ports; only adapters know about a concrete store. Do not import an adapter directly from a service — go through the `db.py` accessor.

The repository singleton is module-level state, initialised in the FastAPI `lifespan` and torn down in reverse order. `get_*_repo()` raises `RuntimeError` if called before init, so no null checks are needed at call sites.

`community/db.py` selects its adapter at runtime from the `db_type` setting (`postgresql` or `dynamodb`), importing the adapter lazily inside the branch. The `db_type` setting is marked for removal in the source.

### Event bus

`shared/events.py` is a minimal in-process pub/sub used to decouple modules. Handlers register with `subscribe(EventType, handler)`; producers call `publish(event)`. Async handlers are scheduled as tasks; handler exceptions are logged, never propagated to the publisher.

This is how `history` observes `matching` without `matching` importing `history`:

```
matching.service._fetch_rooms_all()
  → publish(ActivitySnapshot(rooms))
    → history.event_handlers._handle_activity_snapshot()
      → history.service.record_snapshot()
```

Event types live in `matching/events.py`: `MatchmakingDetected`, `MatchmakingResolved`, `ActivitySnapshot`. Handlers are registered in `history/db.py:init_history_repo()` via `subscribe_events()`.

### Caching

`shared/cache.py` wraps a module-level synchronous `redis` client. All helpers swallow Redis errors and log a warning — a Redis outage degrades to cache misses rather than 500s.

- `cache_get(key)` / `cache_set(key, value, ttl)` — JSON round-trip; `_DataclassEncoder` handles dataclasses and `datetime`.
- `cache_delete_pattern(pattern)` — SCAN-based invalidation, safe in production.

The standard service pattern is read-through:

```python
key = f"ttt2:servers:{com_id}"
if cached := cache_get(key):
    return cached
result = repo.fetch(...)
cache_set(key, result, get_settings().cache_ttl_servers)
return result
```

Routers own cache invalidation on writes (see `community/router.py:_invalidate_posts`).

### Matchmaking detection

`matching/matchmaking_tracker.py` infers who is searching for a match, since RPCN exposes no such state. Players cycling through the TTT2 matchmaking loop (`searchRoom → createRoom → wait → quit`) are only visible while their solo room exists. Consecutive room snapshots are diffed: a player whose `RANK_MATCH` room disappeared is presumed to be searching, and is surfaced as a **phantom room** (`RoomInfoDTO.phantom`) merged into the rank-match group. Entries expire after `matchmaking_ttl` seconds.

The tracker holds module-level state (`_prev_rooms`, `_matchmaking_players`) — it is stateful across requests and not safe to run in multiple processes without coordination.

### RPCN client lifecycle

`matching/rpcn_lifecycle.py` manages one shared `RpcnClient` behind a `threading.Lock`, since the underlying socket is not concurrency-safe. Use the `api_client()` context manager rather than constructing a client:

```python
with api_client() as client:
    rooms = client.search_rooms(...)
```

On `RpcnError` or `OSError` the client is disconnected, the singleton is cleared, and `RpcnUnavailableError` is raised. A `_RECONNECT_COOLDOWN` of 5 s prevents reconnect storms. When `rpcn_metric_enable` is set, the client is wrapped in `TrackedRpcnClient` (`rpcn_client/metrics.py`).

`RpcnUnavailableError` derives from the shared `ServiceUnavailableError`, which `app.py` maps to HTTP 502.

### Error handling

Domain code raises the exceptions in `shared/exceptions.py`; `app.py` registers handlers that map them to status codes. Do not raise `HTTPException` from services.

| Exception | Status |
|-----------|--------|
| `NotFoundError` | 404 |
| `ForbiddenError` | 403 |
| `ValidationError` | 400 |
| `ServiceUnavailableError` | 502 |

### Routes

| Prefix | Router |
|--------|--------|
| *(none)* | `matching/router.py` — `/servers`, `/rooms/all`, `/leaderboard`, `/players/{npid}` |
| `/history` | `history/router.py` — `/stats`, `/stats/daily`, `/stats/weekly-top`, `/players/{npid}` |
| `/community` | `community/router.py` — posts, comments, thumbs, identity |
| *(none)* | `/health` in `app.py`, excluded from the schema |

Community identity is not authentication: `_get_user` reads the `X-Community-User` header or the `community_user` cookie, truncated to 50 characters. There is no verification of who the caller claims to be.

## RPCN protocol (`rpcn_client/`)

A standalone package with no FastAPI dependency, usable via `python -m rpcn_client`.

| Module | Contents |
|--------|----------|
| `constants.py` | `HEADER_SIZE`, `PKT_*`, `CMD_*`, `ERR_*`, `_HDR_FMT` |
| `exceptions.py` | `RpcnError` |
| `models.py` | `LoginInfo`, `RoomAttr`, `RoomBinAttr`, `RoomInfo`, `SearchRoomsResult`, `ScoreEntry`, `ScoreResult` |
| `helpers.py` | `_encode_com_id`, `_read_cstr`, `_pack_protobuf`, `_unpack_data_packet`, `_import_pb2` |
| `client.py` | `RpcnClient` class |
| `metrics.py` | `TrackedRpcnClient` — timing wrapper |
| `__init__.py` | re-exports the full public API |

### Binary protocol framing

All packets share a 15-byte little-endian header (`<BHIQ`):

| Field | Type | Description |
|-------|------|-------------|
| `pkt_type` | u8 | 0=Request, 1=Reply, 2=Notification, 3=ServerInfo |
| `cmd` | u16 | CommandType enum (see `constants.py`) |
| `total_size` | u32 | Header + payload bytes |
| `packet_id` | u64 | Monotonically increasing per-connection counter |

TLS uses `CERT_NONE` because RPCN presents a self-signed certificate.

### Two payload formats

- **Simple commands** (server list, world list): raw `struct.pack` little-endian integers.
- **Complex commands** (rooms, scores): protobuf serialized with a u32 LE length prefix. Use `_pack_protobuf()` to serialize and `_unpack_data_packet()` to deserialize.

### Notification handling

`_recv_reply()` silently discards `PKT_NOTIF` (type 2) packets. The server pushes async notifications (friend status, room events) between request/reply pairs, so the reply loop must skip them rather than erroring.

### Comm IDs

Game communication IDs are exactly 12 ASCII bytes (e.g. `NPWR04850_00`). `_encode_com_id()` validates and encodes them; the result is prepended to most request payloads. TTT2's ID and rank board ID are `TTT2_COM_ID` / `TTT2_RANK_BOARD_ID` in `matching/models.py`.

## Deployment

Docker image built from `python:3.12-alpine`; protobuf is generated during the build. Images go to ECR (`864573346741.dkr.ecr.ap-northeast-2.amazonaws.com/tag2-now/be`).

Production is a **single AWS Lightsail instance** running docker compose — `fe`, `be`, `redis`, `postgres`, `dynamodb-local`. Not ECS. Because there is one process, module-level state (the matchmaking tracker, the shared RPCN client) is safe here but would break under horizontal scaling.

- `.github/workflows/ci.yml` — on PRs to `master`: unit tests, then integration tests against `compose.test.yml`.
- `.github/workflows/deploy.yml` — on `v*` tags: build and push to ECR.

**Release is manual.** SSH into Lightsail and run `docker compose pull && docker compose up -d`, from the directory holding the *instance's own* `compose.yml` and `.env.prod` (not the ones in this repo, which are for local development). RPCN credentials live only in that `.env.prod`.

> **Note:** `deploy.yml` still carries a `deploy` job targeting ECS (`amazon-ecs-render-task-definition` / `amazon-ecs-deploy-task-definition` against `vars.ECS_CLUSTER`). There is no ECS cluster, so the job is gated with `if: false` and never runs; it is kept only so the configuration survives a possible move back to ECS. Only the `build` job is live — **a tag push is not a deploy.**

Full infrastructure notes, including the Athena analytics setup, live in [docs/aws-setup.md](docs/aws-setup.md). The RPCN reference server source is at `C:/project/rpcn`.

Note that `/api` traffic reaches the instance directly and does **not** pass through CloudFront — only static assets do.
