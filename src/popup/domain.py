"""What a popup may hold. Pure rules, with no I/O."""

from hashlib import sha256

from popup.exceptions import InvalidImageError
from popup.models import PopupImage

MAX_TITLE_LENGTH = 100
MAX_BODY_LENGTH = 2000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_HASH_LENGTH = 16


def _sniff(data: bytes) -> str | None:
    """The type the bytes prove. SVG is left out on purpose: it can carry a script."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def parse_image(data: bytes) -> PopupImage:
    """Judge an upload by its bytes; the client's filename and content type prove nothing."""
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImageError("이미지는 5MB를 넘을 수 없습니다.")
    content_type = _sniff(data)
    if content_type is None:
        raise InvalidImageError("PNG, JPEG, WebP, GIF 이미지만 올릴 수 있습니다.")
    return PopupImage(data, content_type, sha256(data).hexdigest()[:_HASH_LENGTH])
