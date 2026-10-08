---
name: test
description: Run the full tag2now test suite before offering a commit in tag2now-BE — this repository's steps in CI's order, plus tag2now-FE's when it changed — and report every step with its counts and the name of every failure. Use whenever a change here is ready to commit, or when asked to run the tests or "everything".
---

# test — the whole suite, from the backend side

Run this before offering a commit.

**This file is one of a pair.** `tag2now-FE/.claude/skills/test/SKILL.md` is the
same run written from the frontend side. Both describe *all* the steps on
purpose: a change here that renames a route breaks the frontend, and the only
check that catches it is step 6, which lives in the other repository. A run
that stopped at this repository's boundary would be the same partial run this
file exists to prevent. **Edit a shared step in both files, or they drift.**

Later steps depend on earlier ones — integration tests need the migration, and
the frontend's contract check needs this repository's schema dumped first. Do
not reorder to save time.

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

| Changed | Run |
|---------|-----|
| Only `tag2now-BE/` | Steps 1–6 (yes, 6 — a route change breaks the frontend's copy) |
| `tag2now-FE/` too | All steps |

**E2E (step 10) runs only when the frontend changed.** It starts a dev server
and a browser and costs minutes; a backend-only change cannot affect it, because
E2E intercepts every API call. Check with `git -C ../tag2now-FE status --short`
rather than guessing.

If `../tag2now-FE` is not checked out beside this repository, run steps 1–5 and
**say plainly that the frontend steps were not run** — do not report a clean run.

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

```bash
.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "not rpcn" > test-results/integration.log 2>&1; echo "exit=$?"
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
diff -u --strip-trailing-cr ../tag2now-FE/src/config/openapi.json openapi.json
```

`--strip-trailing-cr` is required on Windows: git's `core.autocrlf` checks one
copy out with CRLF endings, and a plain `diff -u` then reports every one of its
3,700 lines as changed — a check that always fails tells you nothing.

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

### 7–10. The frontend suites

Run these from `../tag2now-FE` when it changed — the same steps its own `test`
skill describes, where each is explained:

```bash
cd ../tag2now-FE && mkdir -p test-results
cd ../tag2now-FE && npm test > test-results/unit.log 2>&1; echo "exit=$?"                                   # 7.
cd ../tag2now-FE && npm run typecheck > test-results/typecheck.log 2>&1; echo "exit=$?"                     # 8.
cd ../tag2now-FE && npx tsc --noEmit -p e2e/tsconfig.json > test-results/typecheck-e2e.log 2>&1; echo "exit=$?"
cd ../tag2now-FE && npm run lint:css > test-results/lint-css.log 2>&1; echo "exit=$?"                       # 9.
cd ../tag2now-FE && npx playwright test > test-results/e2e.log 2>&1; echo "exit=$?"                         # 10. frontend changes only
```

An E2E failure is named from the summary at the end of `e2e.log` (or
`e2e/test-results/.last-run.json`), and a suspected flake is confirmed with
`npx playwright test --last-failed` — never by re-running the whole suite.

## After the run

**A red suite blocks the commit.** This holds even when the failures look
unrelated to your change: a failure you did not cause is still a failure the
user needs to know about before anything lands. Report it and stop, rather than
committing "since it was already broken".

**A change that spans both repositories needs two commits**, one per repository.
Never commit unless the user explicitly asks — passing tests mean the change is
*ready*, not that it should land.
