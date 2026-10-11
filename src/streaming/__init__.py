"""Streaming channels: players connect their own Chzzk channel, and the rooms
list marks those who are live."""

from streaming.db import close_streaming, init_streaming

# Import entities so Alembic can register the shared metadata without web imports.
import streaming.entities  # noqa: F401

__all__ = ["init_streaming", "close_streaming"]
