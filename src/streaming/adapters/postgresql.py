"""PostgreSQL store for registered streaming channels."""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from streaming.entities import StreamChannelRow
from streaming.exceptions import ChannelTakenError
from streaming.models import PlatformChannel, StreamChannel
from streaming.ports import StreamChannelRepository


def _to_model(row: StreamChannelRow) -> StreamChannel:
    return StreamChannel(
        username=row.username,
        platform=row.platform,
        channel_id=row.channel_id,
        channel_name=row.channel_name,
        registered_at=row.updated_at,
    )


class PostgresStreamChannelRepository(StreamChannelRepository):
    async def get(self, session: AsyncSession, username: str, platform: str) -> StreamChannel | None:
        row = await session.get(StreamChannelRow, (username, platform))
        return _to_model(row) if row else None

    async def list_all(self, session: AsyncSession) -> list[StreamChannel]:
        rows = await session.scalars(select(StreamChannelRow).order_by(StreamChannelRow.updated_at.desc()))
        return [_to_model(row) for row in rows]

    async def upsert(
        self, session: AsyncSession, username: str, platform: str, channel: PlatformChannel
    ) -> StreamChannel:
        stmt = (
            pg_insert(StreamChannelRow)
            .values(
                username=username, platform=platform, channel_id=channel.channel_id, channel_name=channel.channel_name
            )
            .on_conflict_do_update(
                index_elements=["username", "platform"],
                set_={"channel_id": channel.channel_id, "channel_name": channel.channel_name, "updated_at": func.now()},
            )
            .returning(StreamChannelRow)
            .execution_options(populate_existing=True)
        )
        try:
            row = (await session.scalars(stmt)).one()
        except IntegrityError as exc:
            raise ChannelTakenError(
                "이미 다른 계정에 연결된 채널입니다. 본인 채널이라면 관리자에게 문의해 주세요."
            ) from exc
        return _to_model(row)

    async def delete(self, session: AsyncSession, username: str, platform: str) -> bool:
        result = await session.execute(
            delete(StreamChannelRow).where(
                func.lower(StreamChannelRow.username) == username.lower(),
                StreamChannelRow.platform == platform,
            )
        )
        return result.rowcount > 0
