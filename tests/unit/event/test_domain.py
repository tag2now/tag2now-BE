"""The notice's rules and its worked examples."""

import pytest

from event.domain import CHARACTER_COUNT, Baseline, CharState, achievers, judge

PAUL, LAW, LEI = 0, 1, 2
XIAOYU, KUMA, PANDA, MIHARU = 0x07, 0x0B, 0x2B, 0x30

(
    FIRST_DAN,
    SECOND_DAN,
    THIRD_DAN,
    DISCIPLE,
    MENTOR,
    MASTER,
    GRAND_MASTER,
    BRAWLER,
    MARAUDER,
    FIGHTER,
    BERSERKER,
    WARRIOR,
    AVENGER,
    DUELIST,
    PUGILIST,
    VANQUISHER,
    DESTROYER,
    CONQUEROR,
) = range(10, 28)
YAKSA = 35


def baseline(chars: dict[int, int], best: int | None = None, npid: str = "player", rest: int = FIRST_DAN) -> Baseline:
    ranks = [rest] * CHARACTER_COUNT
    for char, rank in chars.items():
        ranks[char] = rank
    return Baseline(npid, tuple(CharState(r, 0, 0) for r in ranks), best if best is not None else max(ranks))


def played(char: int, rank: int, wins: int = 1, losses: int = 0) -> dict:
    return {"id": char, "rank": rank, "wins": wins, "losses": losses}


def reached(player: Baseline, *chars: dict) -> bool:
    return judge(player, chars).best is not None


@pytest.mark.parametrize(
    "top, climbs_to",
    [
        (FIRST_DAN, THIRD_DAN),
        (MENTOR, GRAND_MASTER),
        (FIGHTER, WARRIOR),
        (DUELIST, VANQUISHER),
        (VANQUISHER, DESTROYER),
        (YAKSA, YAKSA + 1),
    ],
)
def test_the_main_needs_two_ranks_or_one_from_orange(top, climbs_to):
    player = baseline({PAUL: top})

    assert not reached(player, played(PAUL, climbs_to - 1))
    assert reached(player, played(PAUL, climbs_to))


def test_a_highest_rank_the_player_has_fallen_from_adds_a_rank():
    # 페카: 역대 푸질, 현재 브로울러 → 기본 2 + 추가 1, 버서커.
    player = baseline({PAUL: BRAWLER}, best=PUGILIST)

    assert not reached(player, played(PAUL, FIGHTER))
    assert reached(player, played(PAUL, BERSERKER))


@pytest.mark.parametrize(
    "best, floor",
    [
        (THIRD_DAN, FIRST_DAN),
        (GRAND_MASTER, SECOND_DAN),
        (BERSERKER, THIRD_DAN),
        (PUGILIST, MASTER),
        (VANQUISHER, BERSERKER),
    ],
)
def test_a_sub_counts_from_the_floor_of_the_highest_rank_ever_reached(best, floor):
    player = baseline({PAUL: best}, rest=FIRST_DAN)

    assert not reached(player, played(LAW, floor + 2))
    assert reached(player, played(LAW, floor + 3))


class TestBacchus:
    """바카스: 현재 푸질, 역대 컨커러, 그래서 부캐는 버서커부터."""

    player = baseline({PAUL: PUGILIST, LAW: AVENGER, LEI: BRAWLER}, best=CONQUEROR, rest=BERSERKER)

    def test_an_avenger_sub_goes_to_vanquisher(self):
        assert not reached(self.player, played(LAW, PUGILIST))
        assert reached(self.player, played(LAW, VANQUISHER))

    def test_a_berserker_sub_goes_to_duelist(self):
        assert reached(self.player, played(3, DUELIST))

    def test_three_ranks_from_below_the_floor_do_not_count(self):
        assert not reached(self.player, played(LEI, BERSERKER))
        assert reached(self.player, played(LEI, DUELIST))


def test_a_sub_close_to_the_main_still_needs_three_ranks():
    # 주캐 뱅퀴, 부캐 푸질 → 컨커까지.
    player = baseline({PAUL: VANQUISHER, LAW: PUGILIST})

    assert not reached(player, played(LAW, DESTROYER))
    assert reached(player, played(LAW, CONQUEROR))


def test_the_three_named_players_start_their_subs_at_pugilist():
    for npid in ("unnamed", "Six_miri", "Daddyking_"):
        assert baseline({PAUL: YAKSA}, npid=npid).sub_floor == PUGILIST
    assert baseline({PAUL: YAKSA}, npid="someone_else").sub_floor == BERSERKER


@pytest.mark.parametrize("first, second", [(KUMA, PANDA), (XIAOYU, MIHARU)])
def test_a_pair_is_one_character(first, second):
    player = baseline({first: DESTROYER, second: MASTER, PAUL: DESTROYER})

    # 곰이 디스면 마스터 팬더를 올려도 부캐가 아니라 곰의 계급을 넘어야 한다.
    assert not reached(player, played(second, GRAND_MASTER + 4))
    assert reached(player, played(second, DESTROYER + 1))


@pytest.mark.parametrize("first, second", [(KUMA, PANDA), (PANDA, KUMA), (XIAOYU, MIHARU), (MIHARU, XIAOYU)])
def test_the_character_climbed_is_the_one_named(first, second):
    player = baseline({PAUL: VANQUISHER, first: BERSERKER, second: BERSERKER})

    standing = judge(player, [played(second, DUELIST)])

    assert standing.best.char_id == second


def test_a_rank_given_to_one_half_is_not_earned_by_playing_the_other():
    player = baseline({PAUL: VANQUISHER, KUMA: BERSERKER, PANDA: BERSERKER})
    given = played(KUMA, DUELIST, wins=0)

    assert not reached(player, given, played(PANDA, BERSERKER))


def test_ranks_on_different_subs_are_not_added_up():
    player = baseline({PAUL: VANQUISHER}, rest=BERSERKER)

    assert not reached(player, played(LAW, AVENGER), played(LEI, WARRIOR))


def test_a_rank_given_without_a_game_is_not_earned():
    player = baseline({PAUL: BRAWLER})

    assert not reached(player, played(PAUL, BERSERKER, wins=0))


def test_a_rank_since_lost_no_longer_shows():
    player = baseline({PAUL: FIRST_DAN})

    assert not reached(player, played(PAUL, SECOND_DAN))


def test_the_climb_that_counts_is_the_players_furthest():
    player = baseline({PAUL: FIRST_DAN}, rest=FIRST_DAN)

    standing = judge(player, [played(PAUL, THIRD_DAN), played(LAW, MENTOR)])

    assert standing.best.char_id == LAW and standing.best.gain == 4


def test_a_player_who_played_on_without_a_rise_has_no_gain():
    standing = judge(baseline({PAUL: MASTER}), [played(PAUL, MASTER)])

    assert standing.best is None and standing.slots[PAUL].played


def test_the_board_ranks_by_climb_and_equal_climbs_share_a_place():
    def climbed(npid: str, to: int):
        return judge(baseline({PAUL: FIRST_DAN}, npid=npid), [played(PAUL, to)])

    far, first, second = climbed("far", DISCIPLE), climbed("first", THIRD_DAN), climbed("second", THIRD_DAN)
    last, nobody = climbed("last", THIRD_DAN), climbed("nobody", SECOND_DAN)

    board = achievers([second, nobody, last, first, far])

    assert [(place, s.baseline.npid) for place, s in board] == [(1, "far"), (2, "first"), (2, "last"), (2, "second")]


def test_only_a_player_never_above_third_dan_is_number_only():
    assert baseline({PAUL: THIRD_DAN}).number_only
    assert not baseline({PAUL: THIRD_DAN}, best=DISCIPLE).number_only
