"""Base domain exception hierarchy."""


class DomainError(Exception):
    """Base for all domain-level errors."""


class NotFoundError(DomainError):
    """Requested entity does not exist."""


class UnauthorizedError(DomainError):
    """Caller is not signed in, or the credential it sent is not valid."""


class ForbiddenError(DomainError):
    """Caller lacks permission for this action."""


class ValidationError(DomainError):
    """Domain rule violated."""


class ConflictError(DomainError):
    """The request is valid but the current state refuses it; retrying later may work."""


class RateLimitedError(DomainError):
    """The caller is acting faster than the service allows; retrying after a pause works."""


class ServiceUnavailableError(DomainError):
    """External service is down or unreachable."""
