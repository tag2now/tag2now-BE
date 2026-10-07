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
# Dev server with reload --- run it from tag2now-BE/, which is where the
# config it needs (env/.env.local) lives.
.venv/Scripts/python.exe -m uvicorn app:app --reload --app-dir src

# Dependencies (Redis, PostgreSQL, DynamoDB Local) + both images
docker compose up

# RPCN client CLI smoke test (connect + login + disconnect)
.venv/Scripts/python.exe -m rpcn_client --user YOUR_USER --password YOUR_PASS
```

**`env/` is resolved from the repository root, not your shell's cwd.**
`settings.py` walks up from its own file (`src/shared/settings.py` → three
parents → `tag2now-BE/env`), so the config is found wherever you launch from.
Look for it at `tag2now-BE/env/.env.local`; a listing from the workspace root
(`D:/project/tag2now`) shows no `env/` and means nothing.

**`env/.env` does not exist, and is not supposed to.** Settings names two files,
`env/.env` and `env/.env.{profile}`, and pydantic-settings treats a missing one
as empty. `.env.local` alone is a complete config. Do not read the absence of
`env/.env` --- or one failed `ls`/`cat` naming it --- as "there is no config":
load `get_settings()` and look at the values before concluding anything.

**A local run does not need its own RPCN account.** Production holds the same
account around the clock, so startup may fail with `LoginAlreadyLoggedIn`. That
is a self-announcing failure with a clear message, not a risk to production and
not something to plan around --- just start the server and read the log. The
RPCN *tests* are the case that genuinely collides (see Tests above).

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
.venv/Scripts/python.exe -m pytest tests/unit/ -v                        # no external services needed
docker compose -f compose.test.yml up -d --wait                          # Redis + PostgreSQL
DATABASE_URL=postgresql+psycopg://tag2now:tag2now@127.0.0.1:5433/tag2now .venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "not rpcn"   # 116, services only
.venv/Scripts/python.exe -m pytest tests/integration/ -v                 # all 129, adds live RPCN
```

- `tests/unit/` — pure logic; no network, no database.
- `tests/integration/` — requires Redis and PostgreSQL from `compose.test.yml`. `tests/integration/test_rpcn_client.py` and `tests/integration/matching/test_service_integration.py` additionally hit the live RPCN server and need valid `RPCN_*` credentials.

**The test stack is not the dev stack.** `compose.test.yml` is its own compose
project (`tag2now-be-test`) on host ports **5433** and **6380**, and
`tests/integration/conftest.py` points the tests there, overriding
`env/.env.local`. They once shared `tag2now-be`/5432 with `compose.yml`: a dev
server's collector wrote live matches into the test database, and the
community tests' `TRUNCATE` wiped the dev server's posts. Startup creates no
tables, hence the `alembic` line above, once per fresh container.

**The `rpcn` marker separates the live-RPCN modules from the rest.** Both live-RPCN modules carry a
module-level `pytestmark = pytest.mark.rpcn`, so `-m "not rpcn"` leaves 116 tests
that need nothing but the two containers. CI runs exactly that: it cannot hold
the account (production is logged in as that user around the clock, and two
overlapping runs would collide with each other besides), so the 13 marked tests
are a local check and nothing more. A second RPCN account would fix the local
collision below, but not the CI one — concurrency and third-party availability
remain.

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

### The published contract

`openapi.json` at the repository root is not generated at build time — it is
committed, because **tag2now-FE checks its API calls against a copy of it**.
Nothing else can catch a rename across the two repositories: the integration
tests here build their own requests, so they only ask this service about names
this service chose, and the frontend's e2e mocks answer with whatever the
frontend already believed.

`test_openapi_contract` fails when the file no longer describes the
application, printing the diff. Regenerate and commit it in the same change:

```bash
.venv/Scripts/python.exe scripts/dump_openapi.py
```

A FastAPI upgrade can move the schema with no route changing. That diff is
worth reading rather than suppressing — it changes the document clients read.

**A route without a `response_model` contributes nothing to the contract**: its
schema serialises as `{}`, so the frontend can assert its path but nothing
about its payload. Twelve routes are in that state, the leaderboard, rooms and
history reads among them.

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

Login needs `rpcn_api_server_url`, `rpcn_api_server_key` and `jwt_secret` (32+
bytes). They default to empty so the app still boots without them, but then
`/auth/login` and every signed-in route answer 502. The last two are
`SecretStr`, because `app.py` logs the whole settings object at startup. Tests
get a `JWT_SECRET` from `tests/conftest.py`, which also provides the
`auth_headers(username)` fixture for signed-in requests.

Cache TTLs are settings, not constants — `cache_ttl_servers`, `cache_ttl_leaderboard`, `cache_ttl_rooms`, `cache_ttl_rooms_all`, `cache_ttl_community`, `cache_ttl_activity`, `cache_ttl_player_hours`, `cache_ttl_player_save`, `matchmaking_ttl`.

## Architecture

Eight modules under `src/` --- six domains plus `auth/` and `admin/` --- a `shared/` layer and the standalone `rpcn_client` package.

| Module | Responsibility |
|--------|----------------|
| `matching/` | Live rooms, leaderboard, player lookup, matchmaking detection |
| `history/` | Persisted snapshots, time-series statistics, the match collector |
| `community/` | Message board — posts, comments, thumbs |
| `reservation/` | Appointments — create, join, edit, cancel |
| `auth/` | RPCN account login; stateless bearer tokens other routers depend on |
| `saves/` | TTT2 saves through tag2now-save-admin: anyone's ranks for the profile, and admins' reads and edits |
| `admin/` | RPCN account moderation (lookup, ban) through rpcn-narco's admin API, and the admin gate other routers use |
| `shared/` | Settings, cache, database, exceptions, and the rpcn-narco API server client `auth/` and `admin/` share (`rpcn_api.py`) |
| `rpcn_client/` | Standalone RPCN protocol client (no FastAPI dependency) |

### Authentication

`auth/` verifies a username and password against rpcn-narco's API server
(`external/users/verify`, via the `AccountVerifier` port) and signs
the answer as an HS256 JWT. Nothing is stored: no session table, no cache
entry. Logout is the client discarding the token, and rotating `jwt_secret`
is the only way to revoke early.

Routers get the caller from `auth.dependencies.current_user` (401 when absent)
or `optional_user`, never by reading a header themselves. **Ownership keys on
`user.username`** --- RPCN's canonical, unique spelling --- stored as
`host_subject` / `subject` / `author_subject` in reservations and as `author` /
`voter` on the board. `online_name` is only ever displayed. Because the
dependency resolves before the body, a signed-in route answers 401, not 422,
to an anonymous request with a bad body. Spec: `docs/spec/07-auth.md`.

`auth/` and `admin/` call the same API server with the same key, through one
`shared.rpcn_api.RpcnApiClient` (one connection pool, opened first in
`lifespan` and closed last). It answers the HTTP response or raises
`RpcnApiNotConfigured` / `RpcnApiUnreachable`; what a status means, and the
Korean message a user sees, stay in each module's adapter.

### Admin

`admin/` forwards to rpcn-narco's `admin/users/info` and `admin/users/ban`,
which want an admin's **password on every call**. This service holds none, so
the admin re-enters it per action and it is passed through, derived, never kept.
`admin.dependencies.admin_user` checks the token's `admin` claim first, but
that claim can be a token's lifetime old: RPCN re-checks the role each time.

A wrong admin password answers **400, not 401** --- the frontend ends the
session on any 401 to a signed-in request. A ban does not revoke the target's
site token; it lapses at expiry. Spec: `docs/spec/08-admin.md`.

### Saves

`saves/` owns TTT2 saves, which live on the RPCN host and are read and written
by the `save-admin` service
([tag2now-save-admin](https://github.com/tag2now/tag2now-save-admin)). It runs
in this repo's `compose.prod.yml` with no published port, so only `be` reaches
it, at `SAVE_ADMIN_URL`. One adapter, one client, two routers:

- **`GET /saves/players/{npid}`** --- public, read-only: anyone's ranks and
  record for the profile panel, through save-admin's key-only
  `GET /player/save`. Cached for `cache_ttl_player_save` (10 min), a missing
  save included.
- **`POST /admin/saves/*`** --- admins only, behind `admin.dependencies.admin_user`
  and the same password-per-action rule as `admin/`. An edit is two calls ---
  `dry_run`, then `expect_sha256` set to the sha256 the preview answered --- and
  an online player is a **409** (`ConflictError`), since the game would
  overwrite the edit. A written edit drops that player's profile cache entry.

The split is by domain, not audience: `saves/` uses `admin/`'s gate and account
errors, and `admin/` knows nothing of saves. Spec: `docs/spec/09-save-admin.md`.

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

`matching/matchmaking_tracker.py` infers matchmaking players RPCN cannot show. A player in the TTT2 matchmaking loop (`searchRoom → createRoom → wait → quit`) is in one of three states — the terms are the owner's, use them exactly:

| State | Meaning | In `search_rooms` |
|-------|---------|-------------------|
| **hosting** | waiting in their own solo `RANK_MATCH` room (`createRoom`) | visible |
| **searching** | browsing other rooms with none of their own (`searchRoom`) | invisible |
| **in match** | in a two-member `RANK_MATCH` room | visible |

Consecutive snapshots are diffed: everyone in a `RANK_MATCH` room that disappeared, hosting or in match, is presumed searching until they appear in a real room again or `matchmaking_ttl` passes. Each searching player is surfaced as a **phantom room** — built by `RoomInfoDTO.phantom()` and merged into the rank-match group. A phantom is how a searching player is shown, not a state of its own.

The tracker holds module-level state (`_prev_rooms`, `_searching_players`) — it is stateful across requests and not safe to run in multiple processes without coordination.

### Match-history collector

`history/collector.py` runs as a background asyncio task started in `lifespan`
and cancelled before the database closes. Every
`match_history_collection_interval_seconds` (default 30) it calls
`matching.service.collect_activity_observation()`, which reads RPCN directly and
bypasses the `/rooms/all` response cache, then records three things:

1. ranked-room participants — `record_daily_matched_players()`
2. player and room counts — `record_activity_snapshot()`
3. rank matches that were not in progress on the previous cycle — `record_snapshot()`

A failed cycle is logged and skipped — the loop is never allowed to die on one
bad poll.

**This is the only writer of history.** Nothing is recorded from HTTP traffic,
so statistics do not depend on anyone having the site open.

A rank match is a two-member `RANK_MATCH` room. The collector keeps the room ids
of the previous cycle in `_prev_rank_match_ids` and writes only the new ones;
the set advances after the write commits, so a failed write is retried next
cycle. A restart empties it, and the unique key
`(room_id, user1_npid, user2_npid, match_date)` on `rank_match_snapshots`
absorbs the matches then seen again.

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
| `UnauthorizedError` | 401, with `WWW-Authenticate: Bearer` |
| `ForbiddenError` | 403 |
| `ValidationError` | 400 |
| `ConflictError` | 409 |
| `RateLimitedError` | 429 |
| `ServiceUnavailableError` | 502 |

FastAPI's own `RequestValidationError` keeps its 422 but is reshaped by a
handler in `app.py`: it answers with a single Korean sentence naming the fields
a user can actually see, via the `_FIELD_LABELS` map, instead of the default
error array. A new user-facing request field belongs in that map.

### Routes

| Prefix | Router |
|--------|--------|
| `/auth` | `auth/router.py` — `POST /login`, `GET /me` |
| `/admin` | `admin/router.py` — `POST /users/lookup`, `POST /users/ban`; admins only |
| `/admin/saves` | `saves/router.py` (`admin_router`) — `POST /show`, `/backups`, `/log`, `/set-rank`, `/set-account-rank`, `/floor`, `/restore`; admins only |
| `/saves` | `saves/router.py` — `GET /players/{npid}`, public |
| *(none)* | `matching/router.py` — `/servers`, `/rooms/all`, `/leaderboard`, `/players/{npid}` |
| `/history` | `history/router.py` — `/stats`, `/stats/daily`, `/stats/weekly-top`, `/players/{npid}` |
| `/community` | `community/router.py` — posts, comments, thumbs |
| `/reservations` | `reservation/router.py` — list, create, read one (`GET /{id}`), edit (`PATCH`), join, cancel |
| *(none)* | `/health` in `app.py`, excluded from the schema |

Every write in `community` and `reservation` requires a bearer token; every read is public.

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

- `.github/workflows/ci.yml` — on pushes and PRs to `master`: unit tests, then the `not rpcn` integration tests against `compose.test.yml`. Both jobs generate the protobuf first; without it `import matching` raises `RpcnError` and collection fails before a single test runs.
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
