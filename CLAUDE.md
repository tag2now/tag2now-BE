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

**Redis is optional.** `shared/cache.py` picks its backend from `redis_url`: set,
and it is `RedisCache`; empty (the default), and it is `DictCache`, an
in-process dict with per-entry TTL. `app.py` runs `redis_health_check()` at
import time and `os._exit(1)`s on failure, but that check returns immediately
when no `redis_url` is configured — so a local run with the setting blank starts
fine and caches in memory.

The dict cache is per-process and dies with it. That is a fine default for a
local run and wrong for production, where the restart would silently drop every
cached value.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/unit/ -v          # no external services needed
docker compose -f compose.test.yml up -d --wait            # Redis + PostgreSQL
.venv/Scripts/python.exe -m pytest tests/integration/ -v   # needs services + RPCN credentials
```

- `tests/unit/` — pure logic; no network, no database.
- `tests/integration/` — requires Redis and PostgreSQL from `compose.test.yml`. `tests/integration/test_rpcn_client.py` and `tests/integration/matching/test_service_integration.py` additionally hit the live RPCN server and need valid `RPCN_*` credentials.

**Stop any running backend before the RPCN tests.** RPCN allows one session per
account, and a dev server logs in at startup with the same `RPCN_USER` the tests
use, so those tests fail with `RpcnError: Login failed: LoginAlreadyLoggedIn`
while one is up. `docker ps` is not enough — a uvicorn started in the venv is not
a container, and one that lost the port to another instance still holds the RPCN
session:

```bash
powershell "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | Where-Object { $_.CommandLine -match 'uvicorn' } | Select-Object ProcessId, CommandLine"
```

Stop every match, run the tests, then start the server again. Killing the parent is enough — the reloader's worker is its child and goes with it.

`pyproject.toml` sets `pythonpath = ["src"]` and `asyncio_mode = "auto"`, so async tests need no `@pytest.mark.asyncio` decorator.

## Configuration

`shared/settings.py` defines a pydantic-settings `Settings` model loaded from `env/.env` plus `env/.env.{profile}`, where profile comes from the `FAST_API_PROFILE` environment variable (default `local`). `get_settings()` is `@lru_cache`d — settings are read once per process.

**Env files are runtime config, never baked into the image.** Only
`env/.env.example` is tracked; `env/.env*` is otherwise gitignored and the
Dockerfile does not copy `env/`. Create your own from the template:

```bash
cp env/.env.example env/.env.dev     # docker compose stack
cp env/.env.example env/.env.local   # local venv run
```

How each environment supplies config:

| Environment | Mechanism | Profile |
|-------------|-----------|---------|
| Local venv | `env/.env.local` read by pydantic-settings | `local` (default) |
| `docker compose` | `env_file: env/.env.dev` injects real env vars | unused |
| Production | instance's own `env_file` | unused |

`FAST_API_PROFILE` therefore only matters for local venv runs. In containers the
image has no `env/` directory, so there is no file for a profile to select —
values arrive as real environment variables, which take precedence anyway.

**The two files are not interchangeable**, and picking the wrong one is the
usual local-setup mistake: `.env.local` is read by a venv run and ignored by
compose, `.env.dev` the reverse. Their hostnames differ accordingly —
`redis://redis:6379` and `postgres:5432` resolve only inside the compose
network, `localhost` only outside it.

Both files are gitignored copies, so their contents drift between machines.
Check what yours actually holds before assuming a service is configured.

Required with no default: `rpcn_user`, `rpcn_password`, `rpcn_token`. Everything
else has one — `redis_url` defaults to `""`, which selects the dict cache.

Cache TTLs are settings, not constants — `cache_ttl_servers`, `cache_ttl_leaderboard`, `cache_ttl_rooms`, `cache_ttl_rooms_all`, `cache_ttl_community`, `cache_ttl_activity`, `cache_ttl_player_hours`, `matchmaking_ttl`.

## Architecture

Five domain modules under `src/`, plus a `shared/` layer and the standalone `rpcn_client` package.

| Module | Responsibility |
|--------|----------------|
| `matching/` | Live rooms, leaderboard, player lookup, matchmaking detection |
| `history/` | Persisted snapshots, time-series statistics, the match collector |
| `community/` | Message board — posts, comments, thumbs |
| `reservation/` | Appointments — create, join, edit, cancel |
| `shared/` | Settings, cache, database, event bus, exceptions, `security/` |
| `rpcn_client/` | Standalone RPCN protocol client (no FastAPI dependency) |

`shared/security/credentials.py` issues the opaque tokens that give a
reservation an owner without an account: `TokenCredentialManager.issue()`
returns the client's token and the SHA-256 form that is stored, so possession
of the token is the whole proof of ownership.

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

`reservation/` is the exception to that accessor rule: its `db.py` **injects**
the repository with `service.configure(_repo)`, and `service.py` keeps its own
`_repository()` guard. Copy the `matching`/`history`/`community` shape for a new
module unless you want the injection seam that makes the service testable
without touching `db.py`.

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

`shared/cache.py` exposes a `CacheBackend` ABC with two implementations,
chosen once at import by `_make_cache()` from whether `redis_url` is set:
`RedisCache` (module-level synchronous `redis` client) or `DictCache`
(thread-safe in-process dict). `cache_get` / `cache_set` /
`cache_delete_pattern` are module-level shims over whichever is active.

`RedisCache` swallows every Redis error and logs a warning — an outage degrades
to cache misses rather than 500s.

- `cache_get(key)` / `cache_set(key, value, ttl)` — JSON round-trip; `_DataclassEncoder` handles dataclasses and `datetime`.
- `cache_delete_pattern(pattern)` — SCAN on Redis (safe in production), `fnmatch` over the keys on the dict backend.

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

`matching/matchmaking_tracker.py` infers who is searching for a match, since RPCN exposes no such state. Players cycling through the TTT2 matchmaking loop (`searchRoom → createRoom → wait → quit`) are only visible while their solo room exists. Consecutive room snapshots are diffed: a player whose `RANK_MATCH` room disappeared is presumed to be searching, and is surfaced as a **phantom room** — built by the `RoomInfoDTO.phantom()` classmethod — merged into the rank-match group. Entries expire after `matchmaking_ttl` seconds.

The tracker holds module-level state (`_prev_rooms`, `_matchmaking_players`) — it is stateful across requests and not safe to run in multiple processes without coordination.

### Match-history collector

`history/collector.py` runs as a background asyncio task started in `lifespan`
and cancelled before the database closes. Every
`match_history_collection_interval_seconds` (default 30) it calls
`matching.service.collect_completed_rank_player_ids()` and records the result
via `history.service.record_daily_matched_players()`. A failed cycle is logged
and skipped — the loop is never allowed to die on one bad poll.

This is a second, independent path from the event bus below: the bus reacts to
whatever `_fetch_rooms_all()` happens to observe, while the collector polls on
its own clock.

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

FastAPI's own `RequestValidationError` keeps its 422 but is reshaped by a
handler in `app.py`: it answers with a single Korean sentence naming the fields
a user can actually see, via the `_FIELD_LABELS` map, instead of the default
error array. A new user-facing request field belongs in that map.

### Routes

| Prefix | Router |
|--------|--------|
| *(none)* | `matching/router.py` — `/servers`, `/rooms/all`, `/leaderboard`, `/players/{npid}` |
| `/history` | `history/router.py` — `/stats`, `/stats/daily`, `/stats/weekly-top`, `/players/{npid}` |
| `/community` | `community/router.py` — posts, comments, thumbs, identity |
| `/reservations` | `reservation/router.py` — list, create, read one (`GET /{id}`), edit (`PATCH`), join, cancel |
| *(none)* | `/health` in `app.py`, excluded from the schema |

Community identity is not authentication: `_get_user` reads the `X-Community-User` header or the `community_user` cookie, truncated to 50 characters. There is no verification of who the caller claims to be.

## RPCN protocol (`rpcn_client/`)

A standalone package with no FastAPI dependency, usable via `python -m rpcn_client`.

| Module | Contents |
|--------|----------|
| `constants.py` | `HEADER_SIZE`, `PROTOCOL_VERSION`, `PKT_*`, the `Cmd` IntEnum, `ERR_NO_ERROR`, `COMMUNICATION_ID_SIZE`, `_HDR_FMT` |
| `exceptions.py` | `RpcnError` |
| `models.py` | `UserInfo`, `RoomAttr`, `RoomBinAttr`, `RoomInfo`, `SearchRoomsResult`, `ScoreEntry`, `ScoreResult` |
| `client.py` | `RpcnClient`, plus the framing helper `_unpack_data_packet` |
| `metrics.py` | `TrackedRpcnClient` — timing wrapper |
| `__main__.py` | the `python -m rpcn_client` smoke-test CLI |
| `__init__.py` | re-exports the full public API |

### Binary protocol framing

All packets share a 15-byte little-endian header (`<BHIQ`):

| Field | Type | Description |
|-------|------|-------------|
| `pkt_type` | u8 | 0=Request, 1=Reply, 2=Notification, 3=ServerInfo |
| `cmd` | u16 | `Cmd` IntEnum (see `constants.py`) |
| `total_size` | u32 | Header + payload bytes |
| `packet_id` | u64 | Monotonically increasing per-connection counter |

TLS uses `CERT_NONE` because RPCN presents a self-signed certificate.

### Two payload formats

- **Simple commands** (server list, world list): raw `struct.pack` little-endian integers.
- **Complex commands** (rooms, scores): protobuf serialized with a u32 LE length prefix. `client.py` packs the prefix at the call site and `_unpack_data_packet()` strips it on the way back.

### Notification handling

`_recv_reply()` silently discards `PKT_NOTIF` (type 2) packets. The server pushes async notifications (friend status, room events) between request/reply pairs, so the reply loop must skip them rather than erroring.

### Comm IDs

Game communication IDs are exactly 12 ASCII bytes. The result is prepended to
most request payloads. TTT2's are `TTT2_COM_ID` (`NPWR02973_00`) and
`TTT2_RANK_BOARD_ID` (`4`) in `matching/models.py`.

## Deployment

Docker image built from `python:3.12-alpine`; protobuf is generated during the build. Images go to ECR (`864573346741.dkr.ecr.ap-northeast-2.amazonaws.com/tag2-now/be`).

Production is a **single AWS Lightsail instance** running docker compose — `fe`, `be`, `redis`, `postgres`, `dynamodb-local`. Not ECS. Because there is one process, module-level state (the matchmaking tracker, the shared RPCN client) is safe here but would break under horizontal scaling.

- `.github/workflows/ci.yml` — on PRs to `master`: unit tests, then integration tests against `compose.test.yml`.
- `.github/workflows/deploy.yml` — on `v*` tags: build and push to ECR, then deploy to production over SSH.

**Release is automatic on a `v*` tag.** The `deploy` job SSHes into Lightsail,
writes `BE_IMAGE_TAG` into the instance's `.env.prod`, pulls, runs
`alembic upgrade head` against the new image, and restarts **only `be`** —
`fe` is released independently by the frontend repo, which pins `FE_IMAGE_TAG`.

This repo owns `compose.prod.yml` for the whole stack; the deploy job scp's it
to the instance, so edit it here rather than on the box. RPCN credentials live
only in the instance's `.env.prod`, which is never touched by the workflow apart
from the `BE_IMAGE_TAG` line.

The SSH and ECR settings are **org-level** secrets/variables on the `tag2now`
org, shared with tag2now-FE; this repo defines only `ECR_REPOSITORY`
(`tag2-now/be`) and its own `production` environment. See the
[Actions configuration](docs/aws-setup.md#actions-configuration) table.

Full infrastructure notes, including the Athena analytics setup, live in [docs/aws-setup.md](docs/aws-setup.md). The RPCN reference server source is at `C:/project/rpcn`.

Note that `/api` traffic reaches the instance directly and does **not** pass through CloudFront — only static assets do.
