"""The Idempotency-Key header a creating route requires."""

from typing import Annotated

from fastapi import Header

MAX_KEY_LENGTH = 255


def idempotency_key(
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=MAX_KEY_LENGTH)],
) -> str:
    return key
