"""Anyone's TTT2 save, read-only: the ranks and records a player profile shows.

The save files live on the RPCN host; tag2now-save-admin's server reads them
(`GET /player/save`). Edits stay in `admin/`, which drops this module's cache
entry for the player it wrote.
"""

from saves.db import close_saves, init_saves

__all__ = ["init_saves", "close_saves"]
