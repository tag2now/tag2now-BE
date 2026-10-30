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
.venv/Scripts/python.exe -m pip install ruff==0.17.1   # lint; the version CI pins
```

The protoc command generates `src/rpcn_client/np2_structs_pb2.py` (not committed). It is required by `search_rooms`, `get_score_range`, and `get_score_npid`, and must be regenerated whenever `np2_structs.proto` changes.

## Python environment

Always use the project virtual environment when running Python commands:

```bash
.venv/Scripts/python.exe -m pytest ...
.venv/Scripts/python.exe -m rpcn_client ...
.venv/Scripts/python.exe -m grpc_tools.protoc ...
```

## Comments

A comment says in one line --- two at most --- *why* the code is as it is, when
the code cannot say it. Not what the code does, and not its history: "used to",
"before this", "changed because" belong in the commit message. Anything longer
goes in this file or `docs/`.

Docstrings follow the same rule.

## Running

The ASGI app is `src/app.py:app`. Note `--app-dir src`, since packages live under `src/`.

```bash
# Dev server with reload --- run it from tag2now-BE/, which is where the
# config it needs (env/.env.local) lives.
.venv/Scripts/python.exe -m uvicorn app:app --reload --app-dir src

# Dependencies (Redis, PostgreSQL) + both images
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

**A local run logs in with its own RPCN account.** `env/.env.local`'s
`RPCN_USER` is not the account production holds around the clock, so a local
server and production do not collide. A local server and the RPCN *tests* do,
since both log in as that one local account (see Tests below).

**Redis is optional.** `shared/cache.py` picks its backend from `redis_url`: set,
and it is `RedisCache`; empty (the default), and it is `DictCache`, an
in-process dict with per-entry TTL. `app.py` runs `redis_health_check()` at
import time and `os._exit(1)`s on failure, but that check returns immediately
when no `redis_url` is configured — so a local run with the setting blank starts
fine and caches in memory.

The dict cache is per-process and dies with it. **Production runs it too:**
`compose.prod.yml` has no `redis` service and the instance's `REDIS_URL` is
empty, so every deploy or restart starts with an empty cache.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/unit/ -v                        # no external services needed
docker compose -f compose.test.yml up -d --wait                          # Redis + PostgreSQL
DATABASE_URL=postgresql+psycopg://tag2now:tag2now@127.0.0.1:5433/tag2now .venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest tests/integration/ -v                 # all 147; stop any local backend first
.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "not rpcn"   # 134, what CI runs
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
module-level `pytestmark = pytest.mark.rpcn`, so `-m "not rpcn"` leaves 134 tests
that need nothing but the two containers. CI runs exactly that, since it has no
RPCN account. Locally the 13 marked tests run with the rest, as `.env.local`'s
account, once every local backend is stopped.

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

**Before offering a commit, run `.claude/skills/test/SKILL.md`.** It is the
whole pre-commit suite — these steps, for this repository only — and the rule
for reading it: each suite runs once, its output goes whole to a file under
`test-results/`, and every failure is named from that run. In a session opened at the workspace
root a sub-repository's skills can be discovered late, hours in, so when `test`
is not in the skill list yet, read that file and follow it anyway.

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

Cache TTLs are settings, not constants — `cache_ttl_servers`, `cache_ttl_leaderboard`, `cache_ttl_rooms_all`, `cache_ttl_community`, `cache_ttl_activity`, `cache_ttl_player_hours`, `cache_ttl_player_save`, `cache_ttl_current_rank_leaderboard`, `cache_ttl_live_streams`, `cache_ttl_stream_channels`, `matchmaking_ttl`.

## Architecture

Nine modules under `src/` --- seven domains plus `auth/` and `admin/` --- a `shared/` layer and the standalone `rpcn_client` package.

| Module | Responsibility |
|--------|----------------|
| `matching/` | Live rooms, leaderboard, matchmaking detection |
| `history/` | Persisted snapshots, time-series statistics, the match collector |
| `community/` | Message board — posts, comments, thumbs |
| `reservation/` | Appointments — create, join, edit, cancel |
| `chat/` | Two-day lobby chat, stored in PostgreSQL, pushed over SSE |
| `auth/` | RPCN account login; stateless bearer tokens other routers depend on |
| `saves/` | TTT2 saves through tag2now-save-admin: anyone's ranks for the profile, and admins' reads and edits |
| `streaming/` | Players' own Chzzk channels, and who in a room is live — carried on `/rooms/all` as each user's `stream` |
| `admin/` | RPCN account moderation (lookup, ban) through rpcn-narco's admin API, and the admin gate other routers use |
| `shared/` | Settings, cache, database, exceptions, TTT2's ids and character/rank tables (`ttt2.py`), and the rpcn-narco API server client `auth/` and `admin/` share (`rpcn_api.py`) |
| `rpcn_client/` | Standalone RPCN protocol client (no FastAPI dependency) |

### Authentication

`auth/` verifies a username and password against rpcn-narco's API server
(`external/users/verify`, via the `AccountVerifier` port) and signs
the answer as an HS256 JWT. Nothing is stored: no session table, no cache
entry. Logout is the client discarding the token, and rotating `jwt_secret`
is the only way to revoke early.

Routers get the caller from `auth.dependencies.current_user` (401 when absent),
never by reading a header themselves. **Ownership keys on
`user.username`** --- RPCN's canonical, unique spelling --- stored as
`host_subject` / `subject` / `author_subject` in reservations and as `author` /
`voter` on the board. `online_name` is only ever displayed. Because the
dependency resolves before the body, a signed-in route answers 401, not 422,
to an anonymous request with a bad body. Spec: `docs/spec/07-auth.md`.

`auth/` and `admin/` call the same API server with the same key, through one
`shared.rpcn_api.RpcnApiClient` (one connection pool, which `container.py` opens
and hands to both). It answers the HTTP response or raises
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
in this repo's `compose.prod.yml`, where `be` reaches it at `SAVE_ADMIN_URL`.
Its port is published on the instance's loopback only (`127.0.0.1:8001`), so
from outside it is reachable through an SSH tunnel and nothing else. One
adapter, one client, two routers:

- **`GET /saves/players/{npid}`** --- public, read-only: anyone's ranks and
  record for the profile panel, through save-admin's key-only
  `GET /player/save`. Cached for `cache_ttl_player_save` (10 min), a missing
  save included.
- **`GET /saves/leaderboard?top=&days=`** --- public: players by current rank, from
  save-admin's key-only `GET /players/top-ranks` (every save's characters; the
  two highest are picked here). Sorted here --- best character's rank, the second's, then their
  points; equal standings share a place. `days` keeps only players whose game
  saved within that many days, ranked among themselves. Cached for
  `cache_ttl_current_rank_leaderboard` (5 min) as each player's two best
  characters, and ranked per request. save-admin rereads only saves whose
  `data_id` changed, so only what the game wrote shows; admin edits do not.
- **`GET /saves/current-rank-holders?rank=&days=&top=`** --- public: players to
  play now at a rank (10, 1st dan, to 42) --- those who *played* a character
  currently there and saved within `days` (default **30**), lowest on the
  leaderboard first, since rank correction lifts a strong player's other
  characters. Filled by the same save-admin call as the leaderboard and cached
  **per rank** (`saves:current-rank-holders:{rank}`, character ids only): every
  cache read parses its whole JSON value on the event loop, and one key of
  every character would be megabytes. Spec 09 has the measurements.
- **`POST /admin/saves/*`** --- admins only, behind `admin.dependencies.admin_user`
  and the same password-per-action rule as `admin/`. An edit is two calls ---
  `dry_run`, then `expect_sha256` set to the sha256 the preview answered --- and
  an online player is a **409** (`ConflictError`), since the game would
  overwrite the edit. A written edit drops that player's profile cache entry.

The split is by domain, not audience: `saves/` uses `admin/`'s gate and account
errors, and `admin/` knows nothing of saves. Spec: `docs/spec/09-save-admin.md`.

### Hexagonal layering

**Follow this pattern when adding a module** (`community/` is the reference).
Each domain module uses the same file layout:

| File | Role |
|------|------|
| `ports.py` | Abstract repository interface (`ABC` with `@abstractmethod`) |
| `adapters/` | Concrete implementations of the port (PostgreSQL, RPCN, HTTP services) |
| `service.py` | A service class that receives its ports in `__init__`; orchestrates them, caching and domain rules |
| `dependencies.py` | The `Depends` provider that hands a route its service from `app.state.container` |
| `router.py` | FastAPI `APIRouter`; takes the service through `Depends`, holds no business logic |
| `models.py` | Pydantic request/response models and domain DTOs |
| `exceptions.py` | Domain-specific exceptions |

Routers depend on services; services depend on ports; only adapters know about
a concrete store.

**`src/container.py` is the composition root.** `build_container(stack)` is the
one place adapters and services are constructed, called from `lifespan` with an
`AsyncExitStack`: each resource is opened with `stack.enter_async_context(...)`,
which registers its close in the same line, so shutdown runs in reverse and a
failure part-way closes exactly what was already open. Code outside a request
(the collector) is handed its services by the lifespan rather than reaching for
them.

A resource is a `shared.resource.AsyncResource`: `init` (optional) and `close`,
and the async context manager built on them. The ports of outbound clients
(`GameServerPort`, `SaveServer`, `StreamPlatform`) extend it, as does
`RpcnApiClient`, so a new adapter is closed at shutdown by being entered.

The database opens first and closes last, through `shared.database.open_database()`.
Its engine and session factory are the one module-level resource left; the
container takes `sessions` from it once and passes it to whatever needs one.

Tests swap a service with FastAPI's own seam,
`app.dependency_overrides[community_service] = lambda: CommunityService(fake_repo)`,
or construct the service directly; neither needs a module patched.
`current_user` and `admin_user` read only the token, so they need no service.

A service that judges time takes a `shared.clock.Clock` (default `SystemClock`),
so its tests pass a fixed one.

### Caching

`shared/cache.py` exposes a `CacheBackend` ABC with two implementations,
chosen once at import by `_make_cache()` from whether `redis_url` is set:
`RedisCache` (module-level synchronous `redis` client) or `DictCache`
(thread-safe in-process dict). `cache_get` / `cache_set` /
`cache_delete` / `cache_delete_pattern` are module-level shims over whichever is active.

`RedisCache` swallows every Redis error and logs a warning — an outage degrades
to cache misses rather than 500s.

- `cache_get(key)` / `cache_set(key, value, ttl)` — JSON round-trip; `_DataclassEncoder` handles dataclasses and `datetime`.
- `cache_delete(key)` — one key, taken literally. Use it whenever the key is known: an npid may contain `[` or `*`.
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

Services invalidate right after a write succeeds, next to the read-through they
invalidate (see `community/service.py`); routers never touch the cache.

### Chat

`chat/` is a lobby chat that shows the current play day and the one before it
--- from the previous day's 06:00 KST (`chat.domain.history_start`), so a
conversation does not look cut off just after dawn. Messages are kept in
**PostgreSQL** (`chat_messages`, `adapters/postgresql.py`), so a deploy keeps
them and their deletions; a snapshot carries the newest 500 in that window.
Ids are an identity column and never repeat across restarts. Deletion removes
the row, and older rows are left in place with no purge job.
`MemoryChatRepository` remains as the unit tests' store. Spec: `docs/spec/10-chat.md`.

`GET /chat/stream` is Server-Sent Events through FastAPI's own
`fastapi.sse.EventSourceResponse`, which also sends a `: ping` every 15 s ---
inside CloudFront's 30 s origin timeout. Every connection opens with a
`snapshot` of the recent messages and then follows `message` and `delete` events;
a reconnect gets a new snapshot rather than resuming from `Last-Event-ID`,
because a deletion missed while disconnected only shows in a whole new list.
Events travel **in memory** on the `ChatEventBus` port;
`adapters/memory_bus.py` gives each stream a bounded queue and drops a stream
whose queue fills. A second process would need a Redis bus behind that port.

**A stream never closes on its own, so uvicorn runs with
`--timeout-graceful-shutdown 5`** (Dockerfile). Without it uvicorn waits for
open connections forever before lifespan shutdown, `docker stop` kills the
process after 10 s, and the collector and database are never closed. Each
stream cut that way logs a `CancelledError` traceback; that is the cost, not a
fault. A local `--reload` run waits the same way --- pass the flag there too,
or close the chat panel before saving.

### Matchmaking detection

`matching/matchmaking_tracker.py` infers matchmaking players RPCN cannot show. A player in the TTT2 matchmaking loop (`searchRoom → createRoom → wait → quit`) is in one of three states — the terms are the owner's, use them exactly:

| State | Meaning | In `search_rooms` |
|-------|---------|-------------------|
| **hosting** | waiting in their own solo `RANK_MATCH` room (`createRoom`) | visible |
| **searching** | browsing other rooms with none of their own (`searchRoom`) | invisible |
| **in match** | in a two-member `RANK_MATCH` room | visible |

Consecutive snapshots are diffed: everyone in a `RANK_MATCH` room that disappeared, hosting or in match, is presumed searching until they appear in a real room again or `matchmaking_ttl` passes. Each searching player is surfaced as a **phantom room** — built by `RoomInfoDTO.phantom()` and merged into the rank-match group. A phantom is how a searching player is shown, not a state of its own.

The tracker is a `MatchmakingTracker` that `MatchingService` holds; its snapshot lives in process memory, so it is stateful across requests and not safe to run in multiple processes without coordination.

`GET /rooms/all` is composed in the router: `MatchingService.get_rooms_all()`
answers the rooms (cached for `cache_ttl_rooms_all`), and
`StreamingService.live_or_empty()` marks each user's `stream` from its own caches.
Matching knows nothing of streaming, and a streaming failure leaves every
`stream` null rather than failing the room list.

### Match-history collector

`history/collector.py`'s `Collector`, built by the container with the matching
and history services, runs as a background asyncio task started in `lifespan`
and cancelled before the database closes. Every
`match_history_collection_interval_seconds` (default 30) it calls
`MatchingService.collect_activity_observation()`, which reads RPCN directly and
bypasses the `/rooms/all` response cache, then records three things:

1. ranked-room participants — `record_daily_matched_players()`
2. player and room counts — `record_activity_snapshot()`
3. rank matches that were not in progress on the previous cycle — `record_snapshot()`

A failed cycle is logged and skipped — the loop is never allowed to die on one
bad poll.

**This is the only writer of history.** Nothing is recorded from HTTP traffic,
so statistics do not depend on anyone having the site open.

A rank match is a two-member `RANK_MATCH` room. The collector instance keeps the room ids
of the previous cycle in `_prev_rank_match_ids` and writes only the new ones;
the set advances after the write commits, so a failed write is retried next
cycle. A restart empties it, and the unique key
`(room_id, user1_npid, user2_npid, match_date)` on `rank_match_snapshots`
absorbs the matches then seen again.

### RPCN client lifecycle

`matching/rpcn_lifecycle.py`'s `SharedRpcnClient` holds one `RpcnClient` behind a `threading.Lock`, since the underlying socket is not concurrency-safe. The container builds one and hands it to `RpcnGameServerAdapter`; use its `api_client()` context manager rather than constructing a client:

```python
with self._rpcn.api_client() as client:
    rooms = client.search_rooms(...)
```

It is given a **client factory**, not a client: `create_client` (connect and log in) with the settings bound by `functools.partial`. It calls the factory on first use and again after every failure, and its unit tests pass a fake one.

On `RpcnError` or `OSError` the client is disconnected and dropped, and `RpcnUnavailableError` is raised; for the next 5 s (`cooldown`) a use fails at once rather than reconnecting. When `rpcn_metric_enable` is set, the client is wrapped in `TrackedRpcnClient` (`rpcn_client/metrics.py`).

`RpcnUnavailableError` derives from the shared `ServiceUnavailableError`, which maps to HTTP 502.

### Error handling

Domain code raises the exceptions in `shared/exceptions.py`; `shared/error_handlers.py` maps them to status codes in one table, `_STATUS`, which `app.py` installs with `register_exception_handlers(app)`. A new exception is one line in that table. Do not raise `HTTPException` from services.

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
handler in `shared/error_handlers.py`: it answers with a single Korean sentence naming the fields
a user can actually see, via the `_FIELD_LABELS` map, instead of the default
error array. A new user-facing request field belongs in that map.

### Routes

| Prefix | Router |
|--------|--------|
| `/auth` | `auth/router.py` — `POST /login`, `GET /me` |
| `/admin` | `admin/router.py` — `POST /users/lookup`, `POST /users/ban`; admins only |
| `/admin/saves` | `saves/router.py` (`admin_router`) — `POST /show`, `/backups`, `/log`, `/set-rank`, `/set-account-rank`, `/floor`, `/restore`; admins only |
| `/saves` | `saves/router.py` — `GET /players/{npid}`, `GET /leaderboard`, `GET /current-rank-holders`, public |
| `/streams` | `streaming/router.py` — `GET`/`PUT`/`DELETE /me`, the signed-in account's channel |
| `/admin/streams` | `streaming/router.py` (`admin_router`) — `GET`, `DELETE /{username}`; admins only, no password |
| *(none)* | `matching/router.py` — `/game-data`, `/servers`, `/rooms/all`, `/leaderboard` |
| `/history` | `history/router.py` — `/stats`, `/stats/daily`, `/stats/weekly-top`, `/players/{npid}` |
| `/community` | `community/router.py` — posts, comments, thumbs |
| `/reservations` | `reservation/router.py` — list, create, read one (`GET /{id}`), edit (`PATCH`), join, cancel |
| `/chat` | `chat/router.py` — `GET /stream` (SSE, public), `POST /messages`, `DELETE /messages/{id}` |
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
`TTT2_RANK_BOARD_ID` (`4`) in `shared/ttt2.py`.

## Deployment

Docker image built from `python:3.12-alpine`; protobuf is generated during the build. Images go to ECR (`864573346741.dkr.ecr.ap-northeast-2.amazonaws.com/tag2-now/be`).

Production is a **single AWS Lightsail instance** running docker compose — `be`, `save-admin`, `fe`, `postgres`; no Redis, no DynamoDB. Not ECS. Because there is one process, in-process state (the matchmaking tracker, the shared RPCN client) is safe here but would break under horizontal scaling.

- `.github/workflows/ci.yml` — on pushes and PRs to `master`: unit tests, then the `not rpcn` integration tests against `compose.test.yml`. Both jobs generate the protobuf first; without it `import matching` raises `RpcnError` and collection fails before a single test runs.
- `.github/workflows/deploy.yml` — on `v*` tags: build and push to ECR, then deploy to production over SSH.

**Release is automatic on a `v*` tag.** The `deploy` job SSHes into Lightsail,
writes `BE_IMAGE_TAG` into the instance's `.env`, pulls, runs
`alembic upgrade head` against the new image, and restarts **only `be`** —
`fe` is released independently by the frontend repo, which pins `FE_IMAGE_TAG`.

This repo owns `compose.prod.yml` for the whole stack; the deploy job scp's it
to the instance as `compose.yml`, so edit it here rather than on the box. Its comments are one
line of *why* each; the explanation lives in this file and in
tag2now-save-admin's README, not in the compose file. RPCN credentials live
only in the instance's `.env`, which is never touched by the workflow apart
from the `BE_IMAGE_TAG` line.

The SSH and ECR settings are **org-level** secrets/variables on the `tag2now`
org, shared with tag2now-FE; this repo defines only `ECR_REPOSITORY`
(`tag2-now/be`) and its own `production` environment. See the
[Actions configuration](docs/aws-setup.md#actions-configuration) table.

Full infrastructure notes, including the Athena analytics setup, live in [docs/aws-setup.md](docs/aws-setup.md). The RPCN server source (rpcn-narco) is at `D:/project/tag2now/rpcn-narco`.

`/api` traffic passes through CloudFront like the static assets do (responses
carry `Via: … cloudfront.net`), but is never cached there: every request is
forwarded to the instance. See [docs/aws-setup.md](docs/aws-setup.md#architecture).
