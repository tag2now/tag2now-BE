"""Finding finished matches between a player's consecutive saves."""

from datetime import datetime, timezone

from records.domain import compare
from records.models import CharRecord, Comparison, FinishedMatch, MatchOutcome, PlayerSave

_AT = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
PAUL, JIN, LAW = 0, 9, 1


def _save(wins=10, losses=5, chars=None, own_chars=()) -> PlayerSave:
    return PlayerSave("alice", 100, _AT, wins, losses, chars or {PAUL: CharRecord(10, 5)}, own_chars)


def test_a_save_with_the_same_record_finishes_nothing():
    assert compare(_save(), _save()) == Comparison()


def test_a_start_save_finishes_nothing():
    assert compare(_save(), _save(own_chars=(PAUL, JIN))) == Comparison()


def test_one_more_win_is_a_won_match():
    before = _save(chars={PAUL: CharRecord(10, 5), JIN: CharRecord(3, 1)})
    after = _save(wins=11, chars={PAUL: CharRecord(11, 5), JIN: CharRecord(4, 1)})
    assert compare(before, after).match == FinishedMatch(MatchOutcome.WIN, (PAUL, JIN))


def test_one_more_loss_is_a_lost_match():
    before = _save(chars={PAUL: CharRecord(10, 5)})
    after = _save(losses=6, chars={PAUL: CharRecord(10, 6)})
    assert compare(before, after).match == FinishedMatch(MatchOutcome.LOSS, (PAUL,))


def test_a_character_played_for_the_first_time_counts():
    before = _save(chars={PAUL: CharRecord(10, 5)})
    after = _save(wins=11, chars={PAUL: CharRecord(10, 5), LAW: CharRecord(1, 0)})
    assert compare(before, after).match.chars == (LAW,)


def test_a_loss_is_not_read_from_the_characters_who_only_won_before():
    before = _save(chars={PAUL: CharRecord(10, 5), JIN: CharRecord(3, 1)})
    after = _save(losses=6, chars={PAUL: CharRecord(10, 6), JIN: CharRecord(3, 1)})
    assert compare(before, after).match.chars == (PAUL,)


def test_the_start_save_gives_the_tag_order():
    before = _save(chars={PAUL: CharRecord(10, 5), JIN: CharRecord(3, 1)}, own_chars=(JIN, PAUL))
    after = _save(wins=11, chars={PAUL: CharRecord(11, 5), JIN: CharRecord(4, 1)})
    assert compare(before, after).match.chars == (JIN, PAUL)


def test_a_start_save_that_disagrees_with_the_record_is_not_trusted():
    before = _save(chars={PAUL: CharRecord(10, 5), JIN: CharRecord(3, 1)}, own_chars=(LAW, JIN))
    after = _save(wins=11, chars={PAUL: CharRecord(11, 5), JIN: CharRecord(4, 1)})
    assert compare(before, after).match.chars == (PAUL, JIN)


def test_without_a_start_save_characters_come_by_id():
    before = _save(chars={PAUL: CharRecord(10, 5), JIN: CharRecord(3, 1)})
    after = _save(wins=11, chars={JIN: CharRecord(4, 1), PAUL: CharRecord(11, 5)})
    assert compare(before, after).match.chars == (PAUL, JIN)


def test_a_result_carried_on_the_next_start_save_still_counts():
    before = _save(chars={PAUL: CharRecord(10, 5)}, own_chars=(PAUL,))
    after = _save(wins=11, chars={PAUL: CharRecord(11, 5)}, own_chars=(JIN, LAW))
    assert compare(before, after).match == FinishedMatch(MatchOutcome.WIN, (PAUL,))


def test_a_win_and_a_loss_between_saves_cannot_be_split():
    assert compare(_save(), _save(wins=11, losses=6)) == Comparison(merged=True)


def test_two_wins_between_saves_cannot_be_split():
    assert compare(_save(), _save(wins=12)) == Comparison(merged=True)


def test_a_restored_save_with_a_lower_record_is_no_match():
    assert compare(_save(), _save(wins=9)) == Comparison(merged=True)


def test_a_save_read_from_save_admin_is_in_utc():
    save = PlayerSave.from_answer(
        {
            "npid": "alice",
            "data_id": 7,
            "saved_utc": "2026-11-02 03:14:15.500000",
            "wins": 1,
            "losses": 2,
            "own_chars": [9, 0],
            "chars": [{"id": 9, "wins": 1, "losses": 2}],
        }
    )
    assert save.saved_at == datetime(2026, 11, 2, 3, 14, 15, 500000, tzinfo=timezone.utc)
    assert save.chars == {9: CharRecord(1, 2)}
    assert save.own_chars == (9, 0)
