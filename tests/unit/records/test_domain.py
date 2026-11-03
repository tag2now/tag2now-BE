"""Finding finished matches between a player's consecutive saves."""

from datetime import datetime, timezone

from records.domain import compare, seat
from records.models import CharTally, Comparison, PlayerMatch, MatchOutcome, MatchPlayer, PlayerSave

_AT = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
PAUL, JIN, LAW = 0, 9, 1


def _save(wins=10, losses=5, tallies=None, entered_chars=()) -> PlayerSave:
    return PlayerSave("alice", 100, _AT, wins, losses, tallies or {PAUL: CharTally(10, 5)}, entered_chars)


def test_a_save_with_the_same_record_finishes_nothing():
    assert compare(_save(), _save()) == Comparison()


def test_a_start_save_finishes_nothing():
    assert compare(_save(), _save(entered_chars=(PAUL, JIN))) == Comparison()


def test_one_more_win_is_a_won_match():
    before = _save(tallies={PAUL: CharTally(10, 5), JIN: CharTally(3, 1)})
    after = _save(wins=11, tallies={PAUL: CharTally(11, 5), JIN: CharTally(4, 1)})
    assert compare(before, after).match == PlayerMatch(MatchOutcome.WIN, (PAUL, JIN), (None, None))


def test_one_more_loss_is_a_lost_match():
    before = _save(tallies={PAUL: CharTally(10, 5)})
    after = _save(losses=6, tallies={PAUL: CharTally(10, 6)})
    assert compare(before, after).match == PlayerMatch(MatchOutcome.LOSS, (PAUL,), (None,))


def test_a_character_played_for_the_first_time_counts():
    before = _save(tallies={PAUL: CharTally(10, 5)})
    after = _save(wins=11, tallies={PAUL: CharTally(10, 5), LAW: CharTally(1, 0)})
    assert compare(before, after).match.chars == (LAW,)


def test_a_loss_is_not_read_from_the_characters_who_only_won_before():
    before = _save(tallies={PAUL: CharTally(10, 5), JIN: CharTally(3, 1)})
    after = _save(losses=6, tallies={PAUL: CharTally(10, 6), JIN: CharTally(3, 1)})
    assert compare(before, after).match.chars == (PAUL,)


def test_the_start_save_gives_the_tag_order():
    before = _save(tallies={PAUL: CharTally(10, 5), JIN: CharTally(3, 1)}, entered_chars=(JIN, PAUL))
    after = _save(wins=11, tallies={PAUL: CharTally(11, 5), JIN: CharTally(4, 1)})
    assert compare(before, after).match.chars == (JIN, PAUL)


def test_a_start_save_that_disagrees_with_the_record_is_not_trusted():
    before = _save(tallies={PAUL: CharTally(10, 5), JIN: CharTally(3, 1)}, entered_chars=(LAW, JIN))
    after = _save(wins=11, tallies={PAUL: CharTally(11, 5), JIN: CharTally(4, 1)})
    assert compare(before, after).match.chars == (PAUL, JIN)


def test_without_a_start_save_characters_come_by_id():
    before = _save(tallies={PAUL: CharTally(10, 5), JIN: CharTally(3, 1)})
    after = _save(wins=11, tallies={JIN: CharTally(4, 1), PAUL: CharTally(11, 5)})
    assert compare(before, after).match.chars == (PAUL, JIN)


def test_a_result_carried_on_the_next_start_save_still_counts():
    before = _save(tallies={PAUL: CharTally(10, 5)}, entered_chars=(PAUL,))
    after = _save(wins=11, tallies={PAUL: CharTally(11, 5)}, entered_chars=(JIN, LAW))
    assert compare(before, after).match == PlayerMatch(MatchOutcome.WIN, (PAUL,), (None,))


def test_a_win_and_a_loss_between_saves_cannot_be_split():
    assert compare(_save(), _save(wins=11, losses=6)) == Comparison(merged=True)


def test_two_wins_between_saves_cannot_be_split():
    assert compare(_save(), _save(wins=12)) == Comparison(merged=True)


def test_a_restored_save_with_a_lower_record_is_no_match():
    assert compare(_save(), _save(wins=9)) == Comparison(merged=True)


# Ranks: the one each character went into the match at.


def test_the_rank_is_the_one_before_the_match():
    before = _save(tallies={PAUL: CharTally(10, 5, 20), JIN: CharTally(3, 1, 18)})
    after = _save(wins=11, tallies={PAUL: CharTally(11, 5, 21), JIN: CharTally(4, 1, 18)})
    assert compare(before, after).match.ranks == (20, 18)


def test_a_character_s_first_match_takes_the_rank_after_it():
    before = _save(tallies={PAUL: CharTally(10, 5, 20)})
    after = _save(wins=11, tallies={PAUL: CharTally(10, 5, 20), LAW: CharTally(1, 0, 14)})
    assert compare(before, after).match.ranks == (14,)


def test_a_state_kept_before_ranks_takes_the_rank_after_the_match():
    before = _save(tallies={PAUL: CharTally(10, 5)})
    after = _save(wins=11, tallies={PAUL: CharTally(11, 5, 21)})
    assert compare(before, after).match.ranks == (21,)


def test_ranks_follow_the_tag_order():
    before = _save(tallies={PAUL: CharTally(10, 5, 20), JIN: CharTally(3, 1, 18)}, entered_chars=(JIN, PAUL))
    after = _save(wins=11, tallies={PAUL: CharTally(11, 5, 20), JIN: CharTally(4, 1, 18)})
    assert compare(before, after).match == PlayerMatch(MatchOutcome.WIN, (JIN, PAUL), (18, 20))


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
    assert save.tallies == {9: CharTally(1, 2)}
    assert save.entered_chars == (9, 0)


def test_a_save_read_from_save_admin_carries_each_character_s_rank():
    save = PlayerSave.from_answer(
        {
            "npid": "alice",
            "data_id": 7,
            "saved_utc": "2026-11-02 03:14:15",
            "wins": 1,
            "losses": 2,
            "own_chars": [],
            "chars": [{"id": 9, "rank": 18, "wins": 1, "losses": 2}],
        }
    )
    assert save.tallies == {9: CharTally(1, 2, 18)}


# Seats: 1P is the room's first member.

_ALICE = MatchPlayer("alice", "Alice", MatchOutcome.WIN, (PAUL,), (20,))
_BOB = MatchPlayer("bob", "Bob", MatchOutcome.LOSS, (JIN,), (18,))


def test_the_player_first_in_the_room_is_1p():
    assert seat(_ALICE, _BOB, "alice") == (_ALICE, _BOB)


def test_the_opponent_first_in_the_room_is_1p_whoever_was_seen():
    assert seat(_ALICE, _BOB, "bob") == (_BOB, _ALICE)


def test_with_no_room_the_side_seen_is_1p():
    assert seat(_ALICE, None, None) == (_ALICE, None)
