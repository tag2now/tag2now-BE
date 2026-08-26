# rpcn-client

A Python client for [RPCN](https://github.com/RPCS3/rpcn), the PSN-compatible multiplayer server used by the [RPCS3](https://rpcs3.net) emulator.

Implements the RPCN binary protocol over TLS to query server/world lists, active rooms, and leaderboards. Includes a FastAPI application that exposes Tekken Tag Tournament 2 RPCN data as a REST API, along with player history, a community board, and match reservations.

## Structure

```
src/
  app.py               # FastAPI app — mounts all routers, exception handlers, lifespan
  __main__.py          # `python -m src` entry point (uvicorn launcher)
  rpcn_client/         # Core library — RPCN TLS transport and protocol
  matching/            # Live RPCN data: servers, rooms, leaderboard, player lookup
  history/             # Player activity statistics and match history
  community/           # Community board (PostgreSQL or DynamoDB backed)
  reservation/         # Match reservations
  shared/              # Settings, Redis cache, SQLAlchemy engine, events, exceptions
alembic/               # PostgreSQL migrations
env/                   # Per-profile .env files (see Configuration)
tests/
  unit/
  integration/
```

Each domain package follows the same hexagonal layout: `router.py` (HTTP) →
`service.py` (logic) → `ports.py` (interfaces) → `adapters/` (implementations).

## Setup

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -e .

# Generate protobuf bindings (required for rooms and leaderboard endpoints)
.venv/Scripts/python.exe -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto
```

The editable install (`pip install -e .`) is what puts `src/` on `sys.path` —
without it the server cannot be started by module name. See [Running](#running).

`src/rpcn_client/np2_structs_pb2.py` is gitignored — regenerate it after every
clean checkout.

## Configuration

### Creating your env file

Configuration is supplied by the runtime and is **never baked into the image**.
Only `env/.env.example` is tracked; every other `env/.env*` is gitignored, and
the Dockerfile does not copy `env/` at all.

Start from the template:

```bash
cp env/.env.example env/.env.dev     # docker compose stack
cp env/.env.example env/.env.local   # local venv run
```

Then fill in `RPCN_USER`, `RPCN_PASSWORD`, and `RPCN_TOKEN` — they have no
defaults and are not distributed with the repository. The remaining values in
the template already match the compose stack.

### How each environment gets its config

| Environment | Mechanism |
|-------------|-----------|
| Local venv | `env/.env.local`, read by pydantic-settings |
| `docker compose` | `env_file: env/.env.dev` in `compose.yml`, injected as real environment variables |
| Production | the instance's own `env_file`, holding the real credentials |

### `FAST_API_PROFILE`

[`src/shared/settings.py`](src/shared/settings.py) loads `env/.env` plus
`env/.env.$PROFILE`, where `FAST_API_PROFILE` selects the profile and defaults
to **`local`**.

This only matters for **local venv runs**. In a container the image has no
`env/` directory, so there is no file for a profile to select — values arrive as
real environment variables, which take precedence over env files anyway.

```bash
FAST_API_PROFILE=dev .venv/Scripts/python.exe -m uvicorn app:app --reload
```

A missing env file is not an error — pydantic-settings skips it silently. If
`RPCN_USER`, `RPCN_PASSWORD`, `RPCN_TOKEN`, or `REDIS_URL` end up unset from
every source, startup fails with
`ValidationError: ... Field required`, because those fields have no defaults.

`REDIS_URL` must be a real URL with a `redis://`, `rediss://`, or `unix://`
scheme. An empty value fails at import time with
`ValueError: Redis URL must specify one of the following schemes` — before
FastAPI even starts.

### Environment variables

**RPCN** — `RPCN_USER`, `RPCN_PASSWORD`, and `RPCN_TOKEN` are required and have no defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `FAST_API_PROFILE` | `local` | Selects `env/.env.$PROFILE` (local venv runs only) |
| `RPCN_USER` | *(required)* | RPCN username |
| `RPCN_PASSWORD` | *(required)* | RPCN password |
| `RPCN_TOKEN` | *(required)* | RPCN token |
| `RPCN_HOST` | `rpcn.mynarco.xyz` | RPCN server host |
| `RPCN_PORT` | `31313` | RPCN server port |
| `RPCN_METRIC_ENABLE` | `false` | Enable RPCN client metrics collection |

**Cache** — `REDIS_URL` is optional. Leave it empty to cache in-process instead; that
cache is per-process and is emptied whenever the container restarts, so it only suits a
single-process deployment. When `REDIS_URL` *is* set, an unreachable Redis is a broken
deployment, not a reason to degrade: the app calls `os._exit(1)` at import time.

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `""` | Redis connection URL; empty means in-process caching |
| `CACHE_TTL_SERVERS` | `3600` | Server list cache TTL (seconds) |
| `CACHE_TTL_LEADERBOARD` | `60` | Leaderboard cache TTL |
| `CACHE_TTL_ROOMS` | `5` | Rooms cache TTL |
| `CACHE_TTL_ROOMS_ALL` | `5` | `/rooms/all` cache TTL |
| `CACHE_TTL_COMMUNITY` | `30` | Community board cache TTL |
| `CACHE_TTL_ACTIVITY` | `300` | Activity statistics cache TTL |
| `CACHE_TTL_PLAYER_HOURS` | `300` | Per-player hourly stats cache TTL |
| `MATCHMAKING_TTL` | `60` | Matchmaking tracker entry TTL |

**Database** — `DB_URL` is read two different ways. If it starts with `postgresql://`
it is used as a complete DSN and `DB_USER`/`DB_PASSWORD`/`DB_NAME` are ignored;
otherwise it is treated as a bare `host:port` and the DSN is assembled from the
other three (see [`shared/database.py`](src/shared/database.py)).

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_URL` | `postgresql://localhost:5432/tag2now` | Full DSN, or bare `host:port` |
| `DB_NAME` | `tag2now` | Database name (bare-host form only) |
| `DB_USER` | `postgres` | Database user (bare-host form only) |
| `DB_PASSWORD` | `postgres` | Database password (bare-host form only) |
| `DB_TYPE` | `postgresql` | Community board backend: `postgresql` or `dynamodb` |
| `DYNAMODB_REGION` | `ap-northeast-2` | DynamoDB region (`DB_TYPE=dynamodb`) |
| `DYNAMODB_TABLE_NAME` | `tag2now-community` | DynamoDB table |
| `DYNAMODB_ENDPOINT_URL` | *(none)* | Override for DynamoDB Local |
| `AWS_ACCESS_KEY_ID` | *(none)* | AWS credentials for DynamoDB |
| `AWS_SECRET_ACCESS_KEY` | *(none)* | AWS credentials for DynamoDB |

**HTTP**

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["*"]` | Allowed CORS origins (JSON list) |

`DB_TYPE` selects the community backend only. History and reservations always
use PostgreSQL, so a working `DB_URL` is required regardless.

## Running

### With docker compose (recommended)

Brings up the backend, frontend, Redis, PostgreSQL, and DynamoDB Local. Reads
its configuration from `env/.env.dev`, so create that file first:

```bash
cp env/.env.example env/.env.dev
docker compose up
```

### Locally

Requires PostgreSQL. Redis is optional — with `REDIS_URL` empty the app caches
in-process. To run with Redis anyway:

```bash
docker run -d -p 6379:6379 redis
```

Run migrations first (see below), then start the server:

```bash
.venv/Scripts/python.exe -m uvicorn app:app --reload
```

Equivalently, `python -m src` takes `--host` (default `0.0.0.0`), `--port`
(default `8000`), and `--reload`, and wraps the same uvicorn call.

Interactive docs at `http://localhost:8000/docs`.

Both commands rely on `pip install -e .` from [Setup](#setup). The editable
install drops a `.pth` file pointing at `src/`, which puts every application
module — including the non-package `app.py` — on `sys.path`. Without the
editable install, pass `--app-dir src` to supply that path manually:

```bash
.venv/Scripts/python.exe -m uvicorn app:app --app-dir src --reload
```

This is what the Docker image does: it runs `pip install .` (non-editable), so
no `.pth` is created and `app.py` is not part of the installed distribution.

The history module uses the `Asia/Seoul` timezone, which needs the IANA database
that Windows does not ship. `requirements.txt` pulls in `tzdata` for this — if
startup fails with `ZoneInfoNotFoundError`, the requirements are not fully
installed.

### In production

The Lightsail instance runs `compose.prod.yml` from a clone of this repository,
alongside a `.env.prod` that it keeps to itself — it holds the RPCN credentials
and is never committed. The database is bind-mounted from the host, so run
compose as the user that owns that directory.

There is no Redis service in production: `REDIS_URL` is left empty, so the
backend caches in-process.

Release a new image:

```bash
git pull
docker compose -f compose.prod.yml pull
docker compose -f compose.prod.yml up -d
```

Pushing a `v*` tag builds and pushes images to ECR, but does **not** deploy —
the commands above are still a manual step.

### Database migrations

PostgreSQL schema changes are managed exclusively by Alembic; application
startup does not create tables. Run migrations before starting the API.

Alembic reads **`DATABASE_URL`** — a separate variable from the application's
`DB_URL`, and it is not read from the `env/` files. Spell the driver out as
`postgresql+psycopg://`: a bare `postgresql://` selects psycopg2, which is not
installed, while `alembic/env.py` builds its own fallback DSN with psycopg 3.

Invoke the `alembic` console script, **not** `python -m alembic` — `-m` puts the
working directory first on `sys.path`, so from the repository root the `alembic/`
migrations directory shadows the installed package.

```bash
# New database
DATABASE_URL=postgresql+psycopg://user:password@host:5432/tag2now \
  .venv/Scripts/alembic.exe upgrade head

# Existing database that already matches the baseline schema (run once)
DATABASE_URL=postgresql+psycopg://user:password@host:5432/tag2now \
  .venv/Scripts/alembic.exe stamp head
```

Use `stamp` only after confirming the existing schema matches the baseline;
it records the revision without applying DDL. Verify later changes with
`alembic check`.

## Endpoints

### Matching — live RPCN data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/servers` | Server and world hierarchy |
| GET | `/rooms/all` | All rooms including hidden ones |
| GET | `/leaderboard` | Top N leaderboard entries with character info |
| GET | `/players/{npid}` | Player lookup by NPID |

### History & statistics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/history/stats` | Hourly player activity (KST) |
| GET | `/history/stats/daily` | Daily summary |
| GET | `/history/stats/weekly-top` | Weekly top players |
| GET | `/history/players/{npid}` | Per-player history |

### Community board

| Method | Path | Description |
|--------|------|-------------|
| POST | `/community/identity` | Set the caller's identity cookie |
| GET | `/community/posts` | List posts |
| POST | `/community/posts` | Create a post |
| GET | `/community/posts/{post_id}` | Post detail with comments |
| DELETE | `/community/posts/{post_id}` | Delete a post |
| POST | `/community/posts/{post_id}/comments` | Add a comment |
| POST | `/community/posts/{post_id}/thumb` | Thumb a post up or down |

### Reservations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/reservations?date=` | Reservations for a date |
| POST | `/reservations` | Create a reservation |
| GET | `/reservations/{id}` | Reservation detail |
| POST | `/reservations/{id}/participants` | Join a reservation |
| DELETE | `/reservations/{id}/participants/me` | Leave (requires `X-Reservation-Token`) |
| DELETE | `/reservations/{id}` | Cancel (requires `X-Reservation-Token`) |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness probe (hidden from the schema) |

## Library usage

```python
from rpcn_client import RpcnClient

with RpcnClient(host="rpcn.mynarco.xyz", port=31313) as client:
    client.connect()
    client.login("username", "password")

    servers = client.get_server_list("NPWR02973_00")
    worlds  = client.get_world_list("NPWR02973_00", servers[0])
    rooms   = client.search_rooms("NPWR02973_00", world_id=worlds[0])
    scores  = client.get_score_range("NPWR02973_00", board_id=0, num_ranks=10)
```

A standalone smoke test against a live server:

```bash
.venv/Scripts/python.exe -m rpcn_client --user you --password secret --token yourtoken
```

## Tests

`tests/unit/` runs without external services. `tests/integration/` needs
PostgreSQL and Redis — `compose.test.yml` provides both:

```bash
docker compose -f compose.test.yml up -d
.venv/Scripts/python.exe -m pytest tests/ -v
```

Some integration tests connect to a live RPCN server and need valid credentials
in the environment.

## Protocol

RPCN uses a 15-byte little-endian header (`<BHIQ`) over TLS with a self-signed certificate:

| Field | Type | Description |
|-------|------|-------------|
| `pkt_type` | u8 | 0=Request, 1=Reply, 2=Notification, 3=ServerInfo |
| `cmd` | u16 | Command type |
| `total_size` | u32 | Header + payload bytes |
| `packet_id` | u64 | Monotonically increasing counter |

Complex commands (rooms, scores) use a protobuf payload with a u32 LE length prefix.
