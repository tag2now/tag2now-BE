"""History module — room snapshot recording and statistics."""

from history.db import init_history_repo, close_history_repo, get_history_repo

# Import entities so Alembic can register the shared metadata without web imports.
import history.entities  # noqa: F401

__all__ = ["init_history_repo", "close_history_repo", "get_history_repo"]
