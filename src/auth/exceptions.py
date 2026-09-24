from shared.exceptions import ForbiddenError, ServiceUnavailableError, UnauthorizedError


class InvalidCredentialsError(UnauthorizedError):
    """Wrong username or password. RPCN does not say which, and neither do we."""


class InvalidTokenError(UnauthorizedError):
    """Missing, malformed, tampered or expired access token."""


class AccountBannedError(ForbiddenError):
    """The password was right, but RPCN has banned the account."""


class AuthUnavailableError(ServiceUnavailableError):
    """Login cannot be answered: RPCN is unreachable or this side is not configured."""
