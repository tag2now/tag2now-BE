"""openapi.json is the contract tag2now-FE checks itself against.

The two repositories share no schema and no codegen, so each side is free to
believe whatever it likes about the other: the backend's integration tests
build their own requests, and the frontend's e2e mocks build their own
responses. Both stay green through a rename that breaks production.

Committing the schema gives them one artifact in common. This test fails when
the code and the committed file disagree, so a change to a route, a model or a
header name arrives as a reviewable diff instead of a silent break.
"""

import difflib
import json
import logging
from pathlib import Path

import pytest

logging.disable(logging.CRITICAL)

CONTRACT = Path(__file__).resolve().parents[2] / "openapi.json"
DIFF_LINES = 40


def _render(schema: dict) -> list[str]:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False).splitlines()


def test_the_committed_schema_matches_the_application():
    from app import app

    # Compared as parsed JSON, not as text: the assertion is about the contract,
    # not about how dump_openapi.py happens to format it. The diff below is
    # rendered only to say what moved.
    generated = json.loads(json.dumps(app.openapi()))
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if generated == committed:
        return

    diff = list(difflib.unified_diff(
        _render(committed), _render(generated),
        fromfile="openapi.json (committed)", tofile="app.openapi() (generated)", lineterm="", n=2,
    ))
    shown = "\n".join(diff[:DIFF_LINES])
    elided = f"\n... {len(diff) - DIFF_LINES} more diff lines" if len(diff) > DIFF_LINES else ""
    pytest.fail(
        f"openapi.json no longer describes the application.\n\n{shown}{elided}\n\n"
        "If the change is intended, regenerate and commit it:\n"
        "    python scripts/dump_openapi.py\n"
        "tag2now-FE checks its API calls against this file, so the diff above is "
        "what the frontend will have to agree with.",
        pytrace=False,
    )
