"""Community board domain exceptions."""

from shared.exceptions import NotFoundError, ForbiddenError, ValidationError


class PostNotFoundError(NotFoundError):
    """Requested post does not exist."""


class CommentNotFoundError(NotFoundError):
    """Requested comment does not exist."""


class OwnershipError(ForbiddenError):
    """Caller does not own the target resource."""


class NestingDepthError(ValidationError):
    """Comment nesting depth exceeded."""
