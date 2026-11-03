"""Finding finished matches by comparing a player's consecutive saves.

Saves are cumulative, so a missed save costs the split between matches and never
the tally. Spec: docs/spec/11-records.md.
"""

from records.models import CharTally, Comparison, MatchOutcome, MatchPlayer, PlayerMatch, PlayerSave

_NO_TALLY = CharTally(0, 0)
_ONE_MATCH = {(1, 0): MatchOutcome.WIN, (0, 1): MatchOutcome.LOSS}


def _count(tally: CharTally, outcome: MatchOutcome) -> int:
    return tally.wins if outcome is MatchOutcome.WIN else tally.losses


def _played(before: PlayerSave, after: PlayerSave, outcome: MatchOutcome) -> tuple[int, ...]:
    """Whose tally rose, in tag order when the start save agrees and by id otherwise."""
    raised = {
        char_id
        for char_id, tally in after.tallies.items()
        if _count(tally, outcome) > _count(before.tallies.get(char_id, _NO_TALLY), outcome)
    }
    return before.entered_chars if set(before.entered_chars) == raised else tuple(sorted(raised))


def _rank_going_in(before: PlayerSave, after: PlayerSave, char_id: int) -> int | None:
    """The save before the match knows the rank it was entered at; a character's first match, or a state
    kept before ranks, falls back to the result's."""
    rank = before.tallies.get(char_id, _NO_TALLY).rank
    return after.tallies[char_id].rank if rank is None else rank


def compare(before: PlayerSave, after: PlayerSave) -> Comparison:
    """A rematch's result arrives on the next start save, so the tally is read before the match state."""
    change = (after.wins - before.wins, after.losses - before.losses)
    if change == (0, 0):
        return Comparison()
    outcome = _ONE_MATCH.get(change)
    if outcome is None:
        return Comparison(merged=True)
    played = _played(before, after, outcome)
    ranks = tuple(_rank_going_in(before, after, char_id) for char_id in played)
    return Comparison(match=PlayerMatch(outcome, played, ranks))


def seat(
    seen: MatchPlayer, opponent: MatchPlayer | None, first_member_npid: str | None
) -> tuple[MatchPlayer, MatchPlayer | None]:
    """1P and 2P, as the game seated them: RPCN lists a room's members by slot, so its first is 1P.
    With no room there is no seat to read, and the player whose save was seen is 1P."""
    if opponent is not None and opponent.npid == first_member_npid:
        return opponent, seen
    return seen, opponent
