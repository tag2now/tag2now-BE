"""Domain exceptions for the rank event."""

from shared.exceptions import NotFoundError


class EventClosedError(NotFoundError):
    """No baseline was loaded, so there is nothing to compare a save with."""


class EventPlayerNotFoundError(NotFoundError):
    """The account had no save when the event began."""
