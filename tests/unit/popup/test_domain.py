"""What counts as an image a popup may show."""

import pytest

from popup.domain import MAX_IMAGE_BYTES, parse_image
from popup.exceptions import InvalidImageError

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16


@pytest.mark.parametrize(
    "data, content_type",
    [
        (PNG, "image/png"),
        (b"\xff\xd8\xff\xe0" + b"\0" * 16, "image/jpeg"),
        (b"GIF89a" + b"\0" * 16, "image/gif"),
        (b"GIF87a" + b"\0" * 16, "image/gif"),
        (b"RIFF\x10\0\0\0WEBP" + b"\0" * 16, "image/webp"),
    ],
)
def test_the_bytes_decide_the_type(data, content_type):
    assert parse_image(data).content_type == content_type


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not an image",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"RIFF\x10\0\0\0WAVE" + b"\0" * 16,
    ],
)
def test_refuses_anything_else(data):
    with pytest.raises(InvalidImageError):
        parse_image(data)


def test_the_size_limit_is_inclusive():
    assert parse_image(PNG.ljust(MAX_IMAGE_BYTES, b"\0")).data

    with pytest.raises(InvalidImageError, match="5MB"):
        parse_image(PNG.ljust(MAX_IMAGE_BYTES + 1, b"\0"))


def test_the_hash_follows_the_content():
    assert parse_image(PNG).hash == parse_image(PNG).hash
    assert parse_image(PNG).hash != parse_image(PNG + b"\1").hash
