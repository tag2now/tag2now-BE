---
description: Run the full tag2now test suite in CI's order — this repository's four steps, plus tag2now-FE's — and report what passed.
---

# /test — the whole suite, from the backend side

Run this before offering a commit.

**This file is one of a pair.** `tag2now-FE/.claude/commands/test.md` is the
same run written from the frontend side. Both describe *all* the steps on
purpose: a change here that renames a route breaks the frontend, and the only
check that catches it is step 6, which lives in the other repository. A command
that stopped at this repository's boundary would be the same partial run this
file exists to prevent. **Edit a shared step in both files, or they drift.**

Later steps depend on earlier ones — integration tests need the migration, and
the frontend's contract check needs this repository's schema dumped first. Do
not reorder to save time.

**Report honestly.** Give pass/fail counts for every step you ran, name any step
you skipped and why, and paste failure output for anything red. A step that
errored for an environment reason is not a pass.

## Scope

| Changed | Run |
|---------|-----|
| Only `tag2now-BE/` | Steps 1–6 (yes, 6 — a route change breaks the frontend's copy) |
| `tag2now-FE/` too | All steps |

**E2E (step 9) runs only when the frontend changed.** It starts a dev server and
a browser and costs minutes; a backend-only change cannot affect it, because E2E
intercepts every API call. Check with `git -C ../tag2now-FE status --short`
rather than guessing.

If `../tag2now-FE` is not checked out beside this repository, run steps 1–5 and
**say plainly that the frontend steps were not run** — do not report a clean run.

## Preconditions

The backend suites need PostgreSQL and Redis:

```bash
docker compose -f compose.test.yml up -d --wait
```

If the Docker daemon is not running, start Docker Desktop and wait for it rather
than skipping the integration tests — they are the half of this suite that
touches SQL, which is where most changes here land.

**`compose.test.yml` and `compose.yml` share a project name and service names**,
so `tag2now-be-postgres-1` is the same container either way, carrying the
persistent `tag2now-be_postgres-data` volume. The database the tests use *is*
the local development database. Do not call it a throwaway and never
`docker compose down -v` it.

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
.venv/Scripts/python.exe -m pytest tests/unit/ -v
```

No external services. Green on master, so a failure here is a regression from
the current change, not pre-existing noise.

### 3. Migrate the database

```bash
.venv/Scripts/python.exe -m alembic upgrade head
```

**Do not skip this, and do not wait for a failure to remember it.** Startup does
not create tables and the container's volume persists across branches, so a
database left on an older revision fails step 4 with
`column "..." of relation "..." does not exist` — dozens of failures that look
like a broken change and are not.

### 4. Integration tests

```bash
.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "not rpcn"
```

`-m "not rpcn"` is the form CI runs and the form to use here. The marked tests
need sole use of the RPCN account, which production holds around the clock, and
a local dev server holds it too. They are a deliberate local-only extra: run the
bare `pytest tests/integration/ -v` only when testing RPCN client behaviour
specifically, after stopping every local backend.

### 5. Refresh the published contract

```bash
.venv/Scripts/python.exe scripts/dump_openapi.py && git diff --stat openapi.json
```

`openapi.json` is committed, not built at deploy time, because tag2now-FE checks
its API calls against a copy of it. `test_openapi_contract` in step 2 fails when
the file no longer describes the app — but it passing does not mean the file is
*committed* up to date after you edit routes. A diff here belongs in the same
commit as the change that caused it.

### 6. Check the frontend's vendored copy

```bash
diff -u ../tag2now-FE/src/config/openapi.json openapi.json
```

CI compares the frontend against the schema published on this repository's
`master`; locally, compare against this working tree, which is what you are
about to commit. A difference means `src/config/openapi.json` over there needs
the new schema copied in and `src/config/contract.test.ts` updated to match —
in tag2now-FE's own commit, since the two repositories are versioned separately.

**This is the only check that sees the seam between the two repositories.** The
integration tests here build their own requests, so they only ask this service
about names this service chose; the frontend mocks the API in unit tests and
intercepts it in E2E. All of them stay green through a rename that breaks
production.

### 7–9. The frontend suites

Run these from `../tag2now-FE` when it changed — the same three steps its own
`/test` describes:

```bash
cd ../tag2now-FE && npm test           # 7. unit and component
cd ../tag2now-FE && npm run typecheck  # 8.
cd ../tag2now-FE && npx playwright test e2e/specs   # 9. E2E — frontend changes only
```

**`e2e/specs`, never a bare `npx playwright test`.** The visual suite under
`e2e/visual` has no committed baseline — `.gitignore` excludes the snapshot
directory outright — so a bare run fails with "a snapshot doesn't exist". CI
excludes it for the same reason.

## After the run

**A red suite blocks the commit.** This holds even when the failures look
unrelated to your change: a failure you did not cause is still a failure the
user needs to know about before anything lands. Report it and stop, rather than
committing "since it was already broken".

**A change that spans both repositories needs two commits**, one per repository.
Never commit unless the user explicitly asks — passing tests mean the change is
*ready*, not that it should land.
