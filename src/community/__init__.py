"""Community board feature — re-exports."""

from community.db import init_db, close_db
from community.router import router

__all__ = ["init_db", "close_db", "router"]
