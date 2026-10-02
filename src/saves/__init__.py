"""TTT2 saves, through tag2now-save-admin's server on the RPCN host.

Two audiences, one domain: anyone reads a player's ranks for the profile panel
(`GET /saves/players/{npid}`, cached), and RPCN admins read and edit saves under
`/admin/saves/*`, with their password checked by RPCN on every call. The admin
gate and the account errors come from `admin/`; nothing there depends on this.
"""

from saves.db import close_saves, init_saves

__all__ = ["init_saves", "close_saves"]
