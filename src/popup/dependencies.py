"""FastAPI dependencies for popups: the service, and the form an admin submits."""

from typing import Annotated

from fastapi import File, Form, Request, UploadFile
from pydantic import AfterValidator, StringConstraints

from popup.domain import MAX_BODY_LENGTH, MAX_IMAGE_BYTES, MAX_TITLE_LENGTH
from popup.models import PopupContent
from popup.service import PopupService


def popup_service(request: Request) -> PopupService:
    return request.app.state.container.popups


def _popup_body(text: str) -> str:
    """A browser sends a form's line breaks as CRLF; the limit should count what the admin typed."""
    body = text.replace("\r\n", "\n").strip()
    if len(body) > MAX_BODY_LENGTH:
        raise ValueError(f"내용은 {MAX_BODY_LENGTH}자를 넘을 수 없습니다.")
    return body


def popup_content(
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_LENGTH), Form()],
    # May stay empty: a popup can be just an image.
    body: Annotated[str, AfterValidator(_popup_body), Form()] = "",
    allow_dismiss_forever: Annotated[bool, Form()] = False,
    allow_dismiss_day: Annotated[bool, Form()] = False,
    active: Annotated[bool, Form()] = False,
) -> PopupContent:
    return PopupContent(title, body, allow_dismiss_forever, allow_dismiss_day, active)


async def uploaded_image(image: Annotated[UploadFile | None, File()] = None) -> bytes | None:
    """One byte past the limit is enough for the size check to refuse it."""
    return await image.read(MAX_IMAGE_BYTES + 1) if image else None
