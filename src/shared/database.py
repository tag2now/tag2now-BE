"""Shared SQLAlchemy async engine and session factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


def build_dsn(driver: str = "asyncpg") -> str:
    """Assemble a PostgreSQL DSN for a driver. db_url carries host:port only.

    The scheme cannot be fixed: SQLAlchemy wants postgresql+asyncpg://, plain
    asyncpg rejects that and wants postgresql://, and Alembic uses psycopg.
    """
    from shared.settings import get_settings

    settings = get_settings()
    scheme = f"postgresql+{driver}" if driver else "postgresql"
    return f"{scheme}://{settings.db_user}:{quote(settings.db_password)}@{settings.db_url}/{settings.db_name}"


async def init_database() -> None:
    """Create the async engine and session factory for an Alembic-managed schema."""
    global _engine, _session_factory

    dsn = build_dsn()

    logger.info(
        "Connecting to database at %s",
        dsn.split("@")[-1] if "@" in dsn else dsn,
    )
    _engine = create_async_engine(dsn, pool_size=10, max_overflow=5)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    logger.info("Database ready")


async def close_database() -> None:
    """Dispose the engine and release all connections."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed")


@asynccontextmanager
async def open_database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """The session factory, for as long as the block runs; the engine is disposed after."""
    await init_database()
    try:
        yield get_session_factory()
    finally:
        await close_database()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, raising if not initialized."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_database() first")
    return _session_factory
