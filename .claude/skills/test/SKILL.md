---
name: test
description: Run tag2now-BE's whole test suite before offering a commit — this repository's steps in CI's order — and report every step with its counts and the name of every failure. Use whenever a change here is ready to commit, or when asked to run the tests or "everything".
---

# test — the whole backend suite

Run this before offering a commit.

## Once per commit, not once per edit

Run the whole suite **once**, when the change is final and a commit is about to
be offered --- not after each edit or rename. While a change is still moving,
run only the test files it touches:

```bash
.venv/Scripts/python.exe -m pytest tests/unit/path/to/test_changed.py -q
```

If an edit lands after the full run, re-run only what that edit touches, unless
it changed something many modules share (`shared/`, `app.py`, a migration).

Later steps depend on earlier ones — the integration tests need the migration.
Do not reorder to save time.

**Report honestly.** Give pass/fail counts for every step you ran, name any step
you skipped and why, and for anything red name each failing test and paste its
error. A step that errored for an environment reason is not a pass.

## Capture first, read second

Every step writes its whole output to a file under `test-results/`
(gitignored). Read the counts and failures **from the file**:

```bash
mkdir -p test-results
.venv/Scripts/python.exe -m pytest tests/unit/ -v > test-results/unit.log 2>&1; echo "exit=$?"
```

**Never filter a run itself through `grep` or `tail`.** Test runners print the
count (`1 failed`) and the names of what failed on separate lines, so a pattern
that keeps one drops the other — the frontend once lost an E2E failure that way
and ran the suite twice more to find it. Each suite runs **once**; a failure is
named from that run. pytest's closing `short test summary info` block lists
every failure by node id.

## Scope

This repository only. A change that also touched tag2now-FE is tested by that
repository's own `test` skill, in its own checkout.

## Preconditions

The integration tests need PostgreSQL and Redis:

```bash
docker compose -f compose.test.yml up -d --wait
```

If the Docker daemon is not running, start Docker Desktop and wait for it rather
than skipping the integration tests — they are the half of this suite that
touches SQL, which is where most changes here land.

**The test stack is not the dev stack.** `compose.test.yml` is its own compose
project (`tag2now-be-test`) on host ports **5433** and **6380**, and
`tests/integration/conftest.py` points the tests there. A database command
meant for the tests must say so — see step 3.

## Steps

### 1. Regenerate protobuf — only if the schema changed

```bash
.venv/Scripts/python.exe -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto
```

`src/rpcn_client/np2_structs_pb2.py` is generated and not committed, so it
already exists on a working machine. Run this only when `np2_structs.proto`
changed or the file is missing — `rpcn_client/client.py` raises on import
without it, which fails collection rather than a test.

### 2. Unit tests

```bash
.venv/Scripts/python.exe -m pytest tests/unit/ -v > test-results/unit.log 2>&1; echo "exit=$?"
```

No external services. Green on master, so a failure here is a regression from
the current change, not pre-existing noise.

### 3. Migrate the test database

```bash
DATABASE_URL=postgresql+psycopg://tag2now:tag2now@127.0.0.1:5433/tag2now .venv/Scripts/python.exe -m alembic upgrade head > test-results/migrate.log 2>&1; echo "exit=$?"
```

**The `DATABASE_URL` is the point of this step.** Without it alembic reads
`env/.env.local` and migrates the *dev* database on 5432, leaving the test
database where it was. Startup creates no tables, so a fresh or stale test
container fails step 4 with `column "..." of relation "..." does not exist` —
dozens of failures that look like a broken change and are not.

### 4. Integration tests

First stop every local backend. The 13 `rpcn`-marked tests log in to live RPCN
as `env/.env.local`'s `RPCN_USER` --- a local account, not production's --- and
RPCN allows one session per account, so a dev server logged in as that user
fails them with `LoginAlreadyLoggedIn`. `docker ps` does not show a venv uvicorn:

```bash
powershell "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | Where-Object { $_.CommandLine -match 'uvicorn' } | Select-Object ProcessId, CommandLine"
```

Stop every match (the reloader's worker goes with its parent), then run all 147:

```bash
.venv/Scripts/python.exe -m pytest tests/integration/ -v > test-results/integration.log 2>&1; echo "exit=$?"
```

Start the server again afterwards if you stopped one. CI runs `-m "not rpcn"`
instead: it has no RPCN account, so the marked tests are checked here or nowhere.

### 5. Lint

```bash
.venv/Scripts/ruff.exe check . > test-results/lint.log 2>&1; echo "exit=$?"
```

CI runs this as its own job. ruff is not in `requirements.txt` (the production
image installs that file), so install it once into the venv at the version CI
pins: `.venv/Scripts/python.exe -m pip install ruff==0.17.1`.

## After the run

**A red suite blocks the commit.** This holds even when the failures look
unrelated to your change: a failure you did not cause is still a failure the
user needs to know about before anything lands. Report it and stop, rather than
committing "since it was already broken".

Never commit unless the user explicitly asks — passing tests mean the change is
*ready*, not that it should land.
