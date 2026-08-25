"""Shared SQLAlchemy async engine, session factory, and transaction decorators."""

import functools
import logging
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


def get_session_factory() -> async_sessionmaker[AsyncSession]:
	"""Return the session factory, raising if not initialized."""
	if _session_factory is None:
		raise RuntimeError("Database not initialized — call init_database() first")
	return _session_factory


# ---------------------------------------------------------------------------
# Transaction decorators
# ---------------------------------------------------------------------------

def transactional(func):
	"""Inject an AsyncSession with an active transaction as the first argument.

	Commits on success, rolls back on exception. Similar to Spring's @Transactional.

	Usage::

		@transactional
		async def create_order(session: AsyncSession, items: list) -> Order:
			...
	"""
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		async with get_session_factory()() as session:
			async with session.begin():
				return await func(session, *args, **kwargs)
	return wrapper


def read_only(func):
	"""Inject an AsyncSession (no explicit transaction) as the first argument.

	For read-only operations that don't need an explicit transaction.

	Usage::

		@read_only
		async def get_users(session: AsyncSession, days: int) -> list:
			...
	"""
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		async with get_session_factory()() as session:
			return await func(session, *args, **kwargs)
	return wrapper
