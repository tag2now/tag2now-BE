"""The saves as the event began, read from a file on the host: one event's data, not code."""

import json
import logging

from event.domain import CHARACTER_COUNT, Baseline, CharState

logger = logging.getLogger(__name__)

_NO_SAVE = CharState(0, 0, 0)


def _baseline(player: dict) -> Baseline:
    chars = [_NO_SAVE] * CHARACTER_COUNT
    for char_id, rank, wins, losses in player["chars"]:
        chars[char_id] = CharState(rank, wins, losses)
    return Baseline(player["npid"], tuple(chars), player["account_rank"], player["new_player"])


def load_baselines(path: str) -> list[Baseline]:
    """Empty without a readable file, so a bad file closes the event and not the site."""
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as file:
            return [_baseline(player) for player in json.load(file)]
    except (OSError, ValueError, LookupError, TypeError):
        logger.exception("Event baseline could not be read: %s", path)
        return []
