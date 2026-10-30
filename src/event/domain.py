"""The 데스활성화 rank event: what each player must reach, and who is there now.

A pure function of the saves when the event began and the saves now. Comparing
the two cannot see a rank reached and lost, so the board is provisional and the
organiser settles those players after the deadline.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import groupby
from typing import Iterable

KST = timezone(timedelta(hours=9))

EVENT_START = datetime(2026, 10, 28, 19, 0, tzinfo=KST)
# Prizes go to this many players; the rest of the board stands behind them.
CAPACITY = 20
CHARACTER_COUNT = 59

# The organiser judges number-only players by hand, so the board only marks them.
THIRD_DAN = 12

_DISCIPLE, _BRAWLER, _WARRIOR, _VANQUISHER = 13, 17, 21, 25
_FIRST_DAN, _SECOND_DAN, _MASTER, _BERSERKER, _PUGILIST = 10, 11, 15, 20, 24
SUB_STEPS = 3

# Kuma and Panda, and Xiaoyu and Miharu, save apart but count as one character,
# so each starts no lower than the other.
_SAME_CHARACTER = {0x0B: 0x2B, 0x2B: 0x0B, 0x07: 0x30, 0x30: 0x07}
# 언나, 육미리 and 빠킹, whose subs the notice starts at Pugilist.
_PUGILIST_START = {"unnamed", "six_miri", "daddyking_"}


@dataclass(frozen=True)
class CharState:
    rank: int
    wins: int
    losses: int


@dataclass(frozen=True)
class Baseline:
    npid: str
    # Rank and record by character id when the event began.
    chars: tuple[CharState, ...]
    # The account rank never drops, so it is the highest rank ever reached.
    account_rank: int
    # Under two weeks old when the event began; the organiser's call, as above.
    new_player: bool = False

    @property
    def top_rank(self) -> int:
        return max(c.rank for c in self.chars)

    @property
    def best_rank(self) -> int:
        return max(self.account_rank, self.top_rank)

    @property
    def main_steps(self) -> int:
        steps = 1 if self.top_rank >= _VANQUISHER else 2
        return steps + 1 if self.best_rank != self.top_rank else steps

    @property
    def sub_floor(self) -> int:
        # Going by the highest rank ever reached, not the current one.
        best = self.best_rank
        if best >= _VANQUISHER:
            return _PUGILIST if self.npid.casefold() in _PUGILIST_START else _BERSERKER
        if best >= _WARRIOR:
            return _MASTER
        if best >= _BRAWLER:
            return THIRD_DAN
        if best >= _DISCIPLE:
            return _SECOND_DAN
        return _FIRST_DAN

    @property
    def number_only(self) -> bool:
        return self.best_rank <= THIRD_DAN


@dataclass(frozen=True)
class Slot:
    char_id: int
    main: bool
    start: int
    steps: int
    rank: int
    # The record changed. A rise without it is the daily floor or an admin's
    # edit, and only a game earns a rank.
    played: bool

    @property
    def target(self) -> int:
        return self.start + self.steps

    @property
    def gain(self) -> int:
        return self.rank - self.start

    @property
    def achieved(self) -> bool:
        return self.played and self.rank >= self.target


@dataclass(frozen=True)
class Standing:
    baseline: Baseline
    slots: tuple[Slot, ...]

    @property
    def best(self) -> Slot | None:
        return max((s for s in self.slots if s.achieved), key=lambda s: s.gain, default=None)


def _slot(baseline: Baseline, char_id: int, now: CharState) -> Slot:
    before = baseline.chars[char_id]
    other = _SAME_CHARACTER.get(char_id)
    rank = before.rank if other is None else max(before.rank, baseline.chars[other].rank)
    main = rank == baseline.top_rank
    return Slot(
        char_id=char_id,
        main=main,
        start=rank if main else max(rank, baseline.sub_floor),
        steps=baseline.main_steps if main else SUB_STEPS,
        rank=now.rank,
        played=(now.wins, now.losses) != (before.wins, before.losses),
    )


def judge(baseline: Baseline, chars: Iterable[dict]) -> Standing:
    """chars is save-admin's list, which leaves out a character with no rank and no record."""
    now = list(baseline.chars)
    for char in chars:
        now[char["id"]] = CharState(char["rank"], char["wins"], char["losses"])
    return Standing(baseline, tuple(_slot(baseline, i, state) for i, state in enumerate(now)))


def achievers(standings: Iterable[Standing]) -> list[tuple[int, Standing]]:
    """Places and players, furthest climb first; equal climbs share a place (1, 2, 2, 4)."""
    done = sorted(
        (s for s in standings if s.best is not None), key=lambda s: (-s.best.gain, s.baseline.npid.casefold())
    )
    board, place = [], 1
    for _, tied in groupby(done, key=lambda s: s.best.gain):
        tied = list(tied)
        board += [(place, s) for s in tied]
        place += len(tied)
    return board
