from shared.exceptions import NotFoundError, ValidationError


class InvalidImageError(ValidationError):
    """The upload is too large, or not an image type a popup may show."""


class PopupNotFoundError(NotFoundError):
    """No popup, or no image on it, under this id."""
