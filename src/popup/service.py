"""Popups admins write and visitors see on opening the site.

The server keeps no record of who dismissed what: visitors may not be signed in,
so that lives in each browser.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth.models import AuthUser
from popup.domain import parse_image
from popup.exceptions import PopupNotFoundError
from popup.models import Popup, PopupContent, PopupImage
from popup.ports import PopupRepository
from shared.cache import cache_delete, cache_get, cache_set
from shared.settings import get_settings

ACTIVE_KEY = "popups:active"
_NOT_FOUND = "팝업을 찾을 수 없습니다."


def _popup_out(popup: Popup) -> dict:
    return {
        "id": popup.id,
        "title": popup.content.title,
        "body": popup.content.body,
        "image_path": f"popups/{popup.id}/image?v={popup.image_hash}" if popup.image_hash else None,
        "allow_dismiss_forever": popup.content.allow_dismiss_forever,
        "allow_dismiss_day": popup.content.allow_dismiss_day,
    }


def _admin_popup_out(popup: Popup) -> dict:
    return {
        **_popup_out(popup),
        "active": popup.content.active,
        "created_by": popup.created_by,
        "created_at": popup.created_at,
        "updated_at": popup.updated_at,
    }


class PopupService:
    def __init__(self, repo: PopupRepository, sessions: async_sessionmaker[AsyncSession]):
        self._repo = repo
        self._sessions = sessions

    # -- visitors ------------------------------------------------------------

    async def list_active(self) -> dict:
        if (cached := cache_get(ACTIVE_KEY)) is not None:
            return cached
        async with self._sessions() as session:
            popups = await self._repo.list_popups(session, active_only=True)
        active = {"popups": [_popup_out(popup) for popup in popups]}
        cache_set(ACTIVE_KEY, active, get_settings().cache_ttl_popups)
        return active

    async def get_image(self, popup_id: int) -> PopupImage:
        async with self._sessions() as session:
            image = await self._repo.get_image(session, popup_id)
        if image is None:
            raise PopupNotFoundError(_NOT_FOUND)
        return image

    # -- admin ---------------------------------------------------------------

    async def list_all(self) -> dict:
        async with self._sessions() as session:
            popups = await self._repo.list_popups(session, active_only=False)
        return {"popups": [_admin_popup_out(popup) for popup in popups]}

    async def create(self, admin: AuthUser, content: PopupContent, image_data: bytes | None) -> dict:
        image = parse_image(image_data) if image_data is not None else None
        async with self._sessions() as session, session.begin():
            popup = await self._repo.create(session, content, image, admin.username)
        cache_delete(ACTIVE_KEY)
        return _admin_popup_out(popup)

    async def update(self, popup_id: int, content: PopupContent, image_data: bytes | None, remove_image: bool) -> dict:
        image = parse_image(image_data) if image_data is not None else None
        async with self._sessions() as session, session.begin():
            popup = await self._repo.update(session, popup_id, content, image, remove_image)
        if popup is None:
            raise PopupNotFoundError(_NOT_FOUND)
        cache_delete(ACTIVE_KEY)
        return _admin_popup_out(popup)

    async def delete(self, popup_id: int) -> None:
        async with self._sessions() as session, session.begin():
            deleted = await self._repo.delete(session, popup_id)
        if not deleted:
            raise PopupNotFoundError(_NOT_FOUND)
        cache_delete(ACTIVE_KEY)
