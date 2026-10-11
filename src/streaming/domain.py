"""Chzzk channel ids and URLs, independent of any I/O."""

import re

CHZZK = "chzzk"

# A channel id is 32 lowercase hex characters, bare or inside any chzzk.naver.com URL.
_CHZZK_CHANNEL_ID = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])")


def parse_chzzk_channel_id(text: str) -> str | None:
    """The channel id in a pasted URL or id, or None when there is none."""
    match = _CHZZK_CHANNEL_ID.search(text.strip().lower())
    return match.group(1) if match else None


def chzzk_live_url(channel_id: str) -> str:
    return f"https://chzzk.naver.com/live/{channel_id}"
