"""PostgreSQL store for popups."""

from dataclasses import asdict

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from popup.entities import PopupRow
from popup.models import Popup, PopupContent, PopupImage
from popup.ports import PopupRepository


def _to_model(row: PopupRow) -> Popup:
    return Popup(
        id=row.id,
        content=PopupContent(
            title=row.title,
            body=row.body,
            allow_dismiss_forever=row.allow_dismiss_forever,
            allow_dismiss_day=row.allow_dismiss_day,
            active=row.active,
        ),
        image_hash=row.image_hash,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _image_values(image: PopupImage | None) -> dict:
    return {
        "image": image.data if image else None,
        "image_type": image.content_type if image else None,
        "image_hash": image.hash if image else None,
    }


class PostgresPopupRepository(PopupRepository):
    async def list_popups(self, session: AsyncSession, active_only: bool) -> list[Popup]:
        query = select(PopupRow).order_by(PopupRow.id.desc())
        if active_only:
            query = query.where(PopupRow.active)
        return [_to_model(row) for row in await session.scalars(query)]

    async def get_image(self, session: AsyncSession, popup_id: int) -> PopupImage | None:
        found = await session.execute(
            select(PopupRow.image, PopupRow.image_type, PopupRow.image_hash).where(
                PopupRow.id == popup_id, PopupRow.image.is_not(None)
            )
        )
        row = found.one_or_none()
        return PopupImage(row.image, row.image_type, row.image_hash) if row else None

    async def create(
        self, session: AsyncSession, content: PopupContent, image: PopupImage | None, created_by: str
    ) -> Popup:
        stmt = (
            insert(PopupRow)
            .values(**asdict(content), **_image_values(image), created_by=created_by)
            .returning(PopupRow)
        )
        return _to_model((await session.scalars(stmt)).one())

    async def update(
        self, session: AsyncSession, popup_id: int, content: PopupContent, image: PopupImage | None, remove_image: bool
    ) -> Popup | None:
        values = {**asdict(content), "updated_at": func.now()}
        if image or remove_image:
            values |= _image_values(image)
        stmt = (
            update(PopupRow)
            .where(PopupRow.id == popup_id)
            .values(**values)
            .returning(PopupRow)
            .execution_options(populate_existing=True)
        )
        row = (await session.scalars(stmt)).one_or_none()
        return _to_model(row) if row else None

    async def delete(self, session: AsyncSession, popup_id: int) -> bool:
        result = await session.execute(delete(PopupRow).where(PopupRow.id == popup_id))
        return result.rowcount > 0
