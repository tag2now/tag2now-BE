from shared.exceptions import ConflictError, NotFoundError, ServiceUnavailableError, ValidationError


class SaveNotFoundError(NotFoundError):
    """The account has never saved TTT2 (no TUS save) --- or, on a profile,
    there is no such account either."""


class BackupNotFoundError(NotFoundError):
    """The account has no backup by that label."""


class SaveConflictError(ConflictError):
    """The save cannot be written now: the player is online, it changed since
    the preview, or the floor would undo demotions."""


class SaveRequestError(ValidationError):
    """The save server refused the request as given."""


class SavesUnavailableError(ServiceUnavailableError):
    """The save server, or the RPCN API behind it, is unreachable, failing, or
    not configured."""
