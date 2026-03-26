"""Shared SQLAlchemy async engine and session factory."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
	"""Shared declarative base for all ORM models."""
	pass


async def init_database() -> None:
	"""Create the async engine, session factory, and all tables."""
	global _engine, _session_factory
	from shared.settings import get_settings

	settings = get_settings()
	dsn = settings.db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

	logger.info(
		"Connecting to database at %s",
		dsn.split("@")[-1] if "@" in dsn else dsn,
	)
	_engine = create_async_engine(dsn, pool_size=10, max_overflow=5)
	_session_factory = async_sessionmaker(_engine, expire_on_commit=False)

	async with _engine.begin() as conn:
		await conn.run_sync(Base.metadata.create_all)

	logger.info("Database ready")


async def close_database() -> None:
	"""Dispose the engine and release all connections."""
	global _engine, _session_factory
	if _engine:
		await _engine.dispose()
		_engine = None
		_session_factory = None
		logger.info("Database engine disposed")


def get_session_factory() -> async_sessionmaker[AsyncSession]:
	"""Return the session factory, raising if not initialized."""
	if _session_factory is None:
		raise RuntimeError("Database not initialized — call init_database() first")
	return _session_factory
