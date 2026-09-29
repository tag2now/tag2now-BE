from shared.exceptions import ForbiddenError, NotFoundError, ServiceUnavailableError, ValidationError


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
    """rpcn-narco's admin API is unreachable, switched off, or not configured."""
