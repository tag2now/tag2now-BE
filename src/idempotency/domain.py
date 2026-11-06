"""What makes two requests the same request."""

import hashlib
import json

from pydantic_core import to_jsonable_python


def fingerprint(scope: str, request: dict) -> str:
    """A digest of the operation and its inputs, so one key cannot be spent on two different writes."""
    canonical = json.dumps(
        {"scope": scope, "request": to_jsonable_python(request)},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
