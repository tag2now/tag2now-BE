"""Moderation for RPCN accounts, run by signed-in RPCN admins.

rpcn-narco stays the authority: every action carries the admin's own password,
which RPCN checks again, so a stale `admin` claim in a token grants nothing.
"""
