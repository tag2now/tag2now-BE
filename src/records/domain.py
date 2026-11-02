"""Finding finished matches by comparing a player's consecutive saves.

Saves are cumulative, so a missed save costs the split between matches and never
the record. Spec: docs/spec/11-records.md.
"""

from records.models import CharRecord, Comparison, FinishedMatch, MatchOutcome, PlayerSave

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


def compare(before: PlayerSave, after: PlayerSave) -> Comparison:
    """A rematch's result arrives on the next start save, so the record is read before the match state."""
    change = (after.wins - before.wins, after.losses - before.losses)
    if change == (0, 0):
        return Comparison()
    result = _ONE_MATCH.get(change)
    if result is None:
        return Comparison(merged=True)
    return Comparison(match=FinishedMatch(result, _played(before, after, result)))
