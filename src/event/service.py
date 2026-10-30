"""The rank event: every player's current save against the one the event began with.

One pass answers the board and every player, so all of them are cached together
for cache_ttl_event rather than asking save-admin for each name searched.
"""

from event import domain
from event.domain import Baseline, Slot, Standing
from event.exceptions import EventClosedError, EventPlayerNotFoundError
from saves.ports import SaveServer
from shared.cache import cache_get, cache_set
from shared.clock import Clock, SystemClock
from shared.settings import get_settings
from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS

_BOARD_KEY = "event:board"


def _player_key(npid: str) -> str:
    return f"event:player:{npid.casefold()}"


def _rank(code: int) -> dict:
    return {"rank": code, **TEKKEN_RANKS[min(code, max(TEKKEN_RANKS))]}


def _char(slot: Slot) -> dict:
    return {"id": slot.char_id, "character": TTT2_CHARACTERS[slot.char_id]}


def _achiever(place: int, standing: Standing) -> dict:
    best = standing.best
    return {
        "place": place,
        "username": standing.baseline.npid,
        "gain": best.gain,
        "main": best.main,
        "char": _char(best),
        "from_rank": _rank(best.start),
        "to_rank": _rank(best.rank),
        "new_player": standing.baseline.new_player,
        "number_only": standing.baseline.number_only,
    }


def _slot(slot: Slot) -> dict:
    return {
        "char": _char(slot),
        "main": slot.main,
        "start": _rank(slot.start),
        "target": _rank(slot.target),
        "rank": _rank(slot.rank),
        "achieved": slot.achieved,
    }


def _slot_order(slot: Slot) -> tuple:
    return not slot.main, not slot.achieved, -slot.gain, slot.char_id


def _player(standing: Standing, place: int | None) -> dict:
    baseline = standing.baseline
    # A main by its other half alone has nothing to show until it is played.
    shown = (s for s in standing.slots if s.played or (s.main and s.rank == baseline.top_rank))
    return {
        "username": baseline.npid,
        "top_rank": _rank(baseline.top_rank),
        "best_rank": _rank(baseline.best_rank),
        "main_steps": baseline.main_steps,
        "sub_steps": domain.SUB_STEPS,
        "sub_floor": _rank(baseline.sub_floor),
        "achieved": standing.best is not None,
        "place": place,
        "new_player": baseline.new_player,
        "number_only": baseline.number_only,
        "slots": [_slot(s) for s in sorted(shown, key=_slot_order)],
    }


class EventService:
    def __init__(self, baselines: list[Baseline], saves: SaveServer, clock: Clock | None = None):
        self._baselines = {b.npid.casefold(): b for b in baselines}
        self._saves = saves
        self._clock = clock or SystemClock()

    def _require_open(self) -> None:
        if not self._baselines:
            raise EventClosedError("진행 중인 이벤트가 없습니다.")

    async def board(self) -> dict:
        self._require_open()
        settings = get_settings()
        end = settings.event_end_at
        if (achievers := cache_get(_BOARD_KEY)) is None:
            achievers = await self._refresh()
        return {
            "start_at": domain.EVENT_START,
            "end_at": end,
            "ended": end is not None and self._clock.now() > end,
            "capacity": domain.CAPACITY,
            "achievers": achievers,
        }

    async def player(self, npid: str) -> dict:
        self._require_open()
        if npid.casefold() not in self._baselines:
            raise EventPlayerNotFoundError("이벤트 시작 때 세이브가 없던 계정입니다.")
        key = _player_key(npid)
        if (cached := cache_get(key)) is None:
            await self._refresh()
            cached = cache_get(key)
        return cached

    async def _refresh(self) -> list[dict]:
        settings = get_settings()
        saved = {player["npid"].casefold(): player["chars"] for player in await self._saves.read_ranks()}
        standings = [domain.judge(b, saved.get(name, [])) for name, b in self._baselines.items()]
        ranked = domain.achievers(s for s in standings if not settings.is_ranking_excluded(s.baseline.npid))
        places = {s.baseline.npid: place for place, s in ranked}

        for standing in standings:
            answer = _player(standing, places.get(standing.baseline.npid))
            cache_set(_player_key(standing.baseline.npid), answer, settings.cache_ttl_event)
        achievers = [_achiever(place, s) for place, s in ranked]
        cache_set(_BOARD_KEY, achievers, settings.cache_ttl_event)
        return achievers
