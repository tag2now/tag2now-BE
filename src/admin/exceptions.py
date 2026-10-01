from shared.exceptions import ConflictError, ForbiddenError, NotFoundError, ServiceUnavailableError, ValidationError


class AdminPasswordError(ValidationError):
    """The admin's re-entered password was wrong.

    A 400, not a 401: the token is fine, and a 401 on a signed-in request makes
    the frontend end the session over a typo.
    """


class NotAdminError(ForbiddenError):
    """The caller is not, or is no longer, an active RPCN admin."""


class AccountNotFoundError(NotFoundError):
    """No RPCN account has exactly that username."""


class SelfBanError(ValidationError):
    """An admin tried to ban their own account."""


class AdminUnavailableError(ServiceUnavailableError):
    """rpcn-narco's admin API, or the save admin server, is unreachable,
    switched off, or not configured."""


class SaveNotFoundError(NotFoundError):
    """The account has never saved TTT2 (no TUS save)."""


class BackupNotFoundError(NotFoundError):
    """The account has no backup by that label."""


class SaveConflictError(ConflictError):
    """The save cannot be written now: the player is online, it changed since
    the preview, or the floor would undo demotions."""


class SaveRequestError(ValidationError):
    """The save admin server refused the request as given."""
