from shared.exceptions import ConflictError, NotFoundError, ServiceUnavailableError, ValidationError


class InvalidChannelError(ValidationError):
    """The input names no channel id."""


class ChannelNotFoundError(NotFoundError):
    """The platform has no such channel, or the account has none registered."""


class ChannelTakenError(ConflictError):
    """Another account already registered this channel."""


class StreamingUnavailableError(ServiceUnavailableError):
    """The streaming platform is unreachable or answered something unexpected."""
