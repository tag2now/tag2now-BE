"""Finding finished matches by comparing a player's consecutive saves.

Saves are cumulative, so a missed save costs the split between matches and never
the record. Spec: docs/spec/11-records.md.
"""

from records.models import CharRecord, Comparison, FinishedMatch, MatchOutcome, MatchSide, PlayerSave

_NO_RECORD = CharRecord(0, 0)
_ONE_MATCH = {(1, 0): MatchOutcome.WIN, (0, 1): MatchOutcome.LOSS}


def _count(record: CharRecord, result: MatchOutcome) -> int:
    return record.wins if result is MatchOutcome.WIN else record.losses


def _played(before: PlayerSave, after: PlayerSave, result: MatchOutcome) -> tuple[int, ...]:
    """Whose record rose, in tag order when the start save agrees and by id otherwise."""
    raised = {
        char_id
        for char_id, record in after.chars.items()
        if _count(record, result) > _count(before.chars.get(char_id, _NO_RECORD), result)
    }
    return before.own_chars if set(before.own_chars) == raised else tuple(sorted(raised))


def _rank_going_in(before: PlayerSave, after: PlayerSave, char_id: int) -> int | None:
    """The save before the match knows the rank it was entered at; a character's first match, or a state
    kept before ranks, falls back to the result's."""
    rank = before.chars.get(char_id, _NO_RECORD).rank
    return after.chars[char_id].rank if rank is None else rank


def compare(before: PlayerSave, after: PlayerSave) -> Comparison:
    """A rematch's result arrives on the next start save, so the record is read before the match state."""
    change = (after.wins - before.wins, after.losses - before.losses)
    if change == (0, 0):
        return Comparison()
    result = _ONE_MATCH.get(change)
    if result is None:
        return Comparison(merged=True)
    played = _played(before, after, result)
    ranks = tuple(_rank_going_in(before, after, char_id) for char_id in played)
    return Comparison(match=FinishedMatch(result, played, ranks))


def seat(own: MatchSide, other: MatchSide | None, room_first: str | None) -> tuple[MatchSide, MatchSide | None]:
    """1P and 2P, as the game seated them: RPCN lists a room's members by slot, so its first is 1P.
    With no room there is no seat to read, and the side whose save was seen is 1P."""
    if other is not None and other.npid == room_first:
        return other, own
    return own, other
