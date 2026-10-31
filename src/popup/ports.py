"""Replaceable contract: where popups are stored."""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from popup.models import Popup, PopupContent, PopupImage


class PopupRepository(ABC):
    @abstractmethod
    async def list_popups(self, session: AsyncSession, active_only: bool) -> list[Popup]:
        """Newest first, without image bytes."""

    @abstractmethod
    async def get_image(self, session: AsyncSession, popup_id: int) -> PopupImage | None: ...

    @abstractmethod
    async def create(
        self, session: AsyncSession, content: PopupContent, image: PopupImage | None, created_by: str
    ) -> Popup: ...

    @abstractmethod
    async def update(
        self, session: AsyncSession, popup_id: int, content: PopupContent, image: PopupImage | None, remove_image: bool
    ) -> Popup | None:
        """Keep the stored image unless given a new one or told to remove it. None when there is no such popup."""

    @abstractmethod
    async def delete(self, session: AsyncSession, popup_id: int) -> bool: ...
