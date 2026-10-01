"""Community board domain exceptions."""

from shared.exceptions import NotFoundError, ForbiddenError, ValidationError


class PostNotFoundError(NotFoundError):
    """Requested post does not exist."""


class CommentNotFoundError(NotFoundError):
    """Requested comment does not exist."""


class OwnershipError(ForbiddenError):
    """Caller does not own the target resource."""


class NoticeAdminOnlyError(ForbiddenError):
    """A non-admin tried to post a notice, or to turn a post into one."""


class NestingDepthError(ValidationError):
    """Comment nesting depth exceeded."""
