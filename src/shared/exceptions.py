"""Base domain exception hierarchy."""


class DomainError(Exception):
    """Base for all domain-level errors."""


class NotFoundError(DomainError):
    """Requested entity does not exist."""


class ForbiddenError(DomainError):
    """Caller lacks permission for this action."""


class ValidationError(DomainError):
    """Domain rule violated."""


class ServiceUnavailableError(DomainError):
    """External service is down or unreachable."""
