"""Idempotency domain exceptions."""

from shared.exceptions import UnprocessableError


class IdempotencyKeyReusedError(UnprocessableError):
    """The key was already used for a different request."""
