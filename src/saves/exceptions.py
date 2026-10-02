from shared.exceptions import NotFoundError, ServiceUnavailableError


class PlayerSaveNotFoundError(NotFoundError):
    """No account by that name, or one that has never saved TTT2."""


class SavesUnavailableError(ServiceUnavailableError):
    """The save server is unreachable, failing, or not configured."""
