"""Current-rank rules are pure — they need no server and no cache."""

from datetime import datetime, timezone

from saves.domain import HOLDER_RANKS, holders_by_rank, holds_its_rank, saved_within, top_two

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _char(id: int, rank: int, points: int = 0, wins: int = 1, losses: int = 0) -> dict:
    return {
        "id": id,
        "character": f"C{id}",
        "rank": rank,
        "rank_name": f"R{rank}",
        "tier": "t",
        "points": points,
        "streak": 0,
        "wins": wins,
        "losses": losses,
    }


def _player(npid: str, *chars: dict, saved_utc: str = "2026-10-30 11:00:00") -> dict:
    return {"npid": npid, "saved_utc": saved_utc, "account_rank": 20, "chars": list(chars)}


def test_the_two_best_characters_by_rank_then_points():
    chars = [_char(1, 20), _char(2, 25), _char(3, 25, points=50)]

    assert [c["id"] for c in top_two(chars)] == [3, 2]


def test_a_tie_keeps_the_lower_id():
    chars = [_char(4, 22), _char(9, 22), _char(2, 22)]

    assert [c["id"] for c in top_two(chars)] == [4, 9]


def test_a_character_played_at_a_holder_rank_holds_it():
    assert holds_its_rank(_char(0, 15, wins=0, losses=1))


def test_a_character_never_played_holds_no_rank():
    assert not holds_its_rank(_char(0, 15, wins=0, losses=0))


def test_no_one_holds_a_rank_below_first_dan():
    assert not holds_its_rank(_char(0, HOLDER_RANKS.start - 1))


def test_holders_are_listed_under_each_rank_they_play_with_their_place():
    players = [
        _player("Alice", _char(1, 20), _char(2, 20), _char(3, 25)),
        _player("Bob", _char(4, 20), _char(5, 30, wins=0)),
    ]

    by_rank = holders_by_rank(players, {"Alice": 1, "Bob": 2})

    assert [(h["npid"], h["place"], h["chars"]) for h in by_rank[20]] == [("Alice", 1, [1, 2]), ("Bob", 2, [4])]
    assert [h["npid"] for h in by_rank[25]] == ["Alice"]
    assert by_rank[30] == []


def test_every_holder_rank_is_listed_even_when_empty():
    assert list(holders_by_rank([], {})) == list(HOLDER_RANKS)


def test_saved_within_keeps_saves_from_the_last_days_boundary_included():
    players = [
        _player("Edge", saved_utc="2026-10-23 12:00:00"),
        _player("Older", saved_utc="2026-10-23 11:59:59"),
    ]

    assert [p["npid"] for p in saved_within(players, 7, NOW)] == ["Edge"]


def test_saved_within_without_days_keeps_everyone():
    players = [_player("Ancient", saved_utc="2020-01-01 00:00:00")]

    assert saved_within(players, None, NOW) == players
