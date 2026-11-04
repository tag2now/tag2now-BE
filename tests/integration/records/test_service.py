"""Match records against PostgreSQL: the outbox, the queue's locks and joining both sides.

The save server is stubbed; the service, both adapters and the tables are real.
The service commits, so rows are removed by npid.
Run with: pytest tests/integration/records/ -v
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, or_, select

from history.adapters.postgresql import PostgresHistoryAdapter
from history.entities import RankMatchSnapshotRow
from history.models import RankMatchSnapshotRecord
from history.service import HistoryService
from records.adapters.postgresql import PostgresRecordsAdapter
from records.entities import MatchEventRow, MatchRow, SaveStateRow
from records.service import RecordsService
from shared.clock import Clock
from shared.database import close_database, get_session_factory, init_database
from shared.ttt2 import TEKKEN_RANKS

ALICE, BOB, CAROL = "records-alice", "records-bob", "records-carol"
_NPIDS = [ALICE, BOB, CAROL]
_START = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
_ROOM_ID = 909090


class _Clock(Clock):
    def __init__(self):
        self.at = _START + timedelta(hours=1)

    def now(self) -> datetime:
        return self.at


async def _clean():
    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(MatchRow).where(or_(MatchRow.p1_npid.in_(_NPIDS), MatchRow.p2_npid.in_(_NPIDS))))
        await session.execute(delete(MatchEventRow).where(MatchEventRow.npid.in_(_NPIDS)))
        await session.execute(delete(SaveStateRow).where(SaveStateRow.npid.in_(_NPIDS)))
        await session.execute(delete(RankMatchSnapshotRow).where(RankMatchSnapshotRow.user1_npid.in_(_NPIDS)))


@pytest_asyncio.fixture
async def world():
    await init_database()
    await _clean()
    history = HistoryService(PostgresHistoryAdapter(), get_session_factory())
    saves = AsyncMock()
    clock = _Clock()
    records = RecordsService(PostgresRecordsAdapter(), get_session_factory(), saves, history, clock)
    yield records, saves, history, clock
    await _clean()
    await close_database()


def _save(
    npid: str, data_id: int, wins: int = 0, losses: int = 0, at: datetime = _START, chars=(0,), rank: int = 20
) -> dict:
    return {
        "npid": npid,
        "data_id": data_id,
        "saved_utc": at.strftime("%Y-%m-%d %H:%M:%S"),
        "wins": wins,
        "losses": losses,
        "own_chars": [],
        "chars": [{"id": char, "rank": rank, "wins": wins, "losses": losses} for char in chars],
    }


async def _capture(records, saves, *answers):
    saves.read_changed.return_value = list(answers)
    await records.capture()


async def _open_room(history, npid1=ALICE, npid2=BOB, room_id=_ROOM_ID, until=_START + timedelta(minutes=30)):
    room = RankMatchSnapshotRecord(room_id, 10, npid1, npid1, npid2, npid2, _START)
    await history.record_snapshot([room])
    await history.touch_rank_matches([room], until)


async def _rows(entity, *where):
    async with get_session_factory()() as session:
        return list((await session.execute(select(entity).where(*where).order_by(entity.id))).scalars())


async def _rows_of_state(npid):
    async with get_session_factory()() as session:
        return list((await session.execute(select(SaveStateRow).where(SaveStateRow.npid == npid))).scalars())


async def _drain(records):
    while await records.process_next():
        pass


async def _matches():
    async with get_session_factory()() as session:
        players = or_(MatchRow.p1_npid.in_(_NPIDS), MatchRow.p2_npid.in_(_NPIDS))
        return list((await session.execute(select(MatchRow).where(players).order_by(MatchRow.id))).scalars())


def _shape(match):
    """(1P, 2P, winning side, 1P's save seen, 2P's save seen)."""
    return match.p1_npid, match.p2_npid, match.winner, match.p1_event_id is not None, match.p2_event_id is not None


# --- outbox ---------------------------------------------------------------------


async def test_a_match_and_its_state_commit_together(world, monkeypatch):
    records, saves, _, _ = world
    await _capture(records, saves, _save(ALICE, 1))
    monkeypatch.setattr(records._repo, "add_event", AsyncMock(side_effect=RuntimeError("write failed")))

    await _capture(records, saves, _save(ALICE, 2, wins=1))

    [state] = await _rows_of_state(ALICE)
    assert (state.data_id, state.wins) == (1, 0)
    assert await _rows(MatchEventRow, MatchEventRow.npid == ALICE) == []


async def test_a_save_read_again_queues_its_match_once(world):
    records, saves, _, _ = world
    await _capture(records, saves, _save(ALICE, 1))
    await _capture(records, saves, _save(ALICE, 2, wins=1))
    await _capture(records, saves, _save(ALICE, 2, wins=1))

    assert len(await _rows(MatchEventRow, MatchEventRow.npid == ALICE)) == 1


async def test_a_jump_is_counted_on_the_state(world):
    records, saves, _, _ = world
    await _capture(records, saves, _save(ALICE, 1))
    await _capture(records, saves, _save(ALICE, 2, wins=3))

    [state] = await _rows_of_state(ALICE)
    assert (state.wins, state.merged_count) == (3, 1)
    assert await _rows(MatchEventRow, MatchEventRow.npid == ALICE) == []


async def test_the_comparison_survives_the_round_trip_through_the_table(world):
    records, saves, _, _ = world
    first = _save(ALICE, 1, wins=4, chars=(9,))
    first["own_chars"] = [9, 0]
    await _capture(records, saves, first)

    after = _save(ALICE, 2, wins=5, chars=(9,))
    after["chars"].append({"id": 0, "wins": 1, "losses": 0})
    await _capture(records, saves, after)

    [event] = await _rows(MatchEventRow, MatchEventRow.npid == ALICE)
    assert (event.result, event.chars) == ("win", [9, 0])


# --- queue ----------------------------------------------------------------------


async def _queued_wins(records, saves, count=2):
    for index, npid in enumerate(_NPIDS[:count]):
        await _capture(records, saves, _save(npid, 10 + index))
        await _capture(records, saves, _save(npid, 20 + index, wins=1))


async def test_two_consumers_never_hold_the_same_event(world):
    records, saves, _, clock = world
    await _queued_wins(records, saves)
    factory = get_session_factory()

    async with factory() as first, first.begin(), factory() as second, second.begin():
        one = await records._repo.claim_event(first, clock.now())
        other = await records._repo.claim_event(second, clock.now())

    assert one is not None and other is not None
    assert one.id != other.id


async def test_a_crash_while_holding_an_event_leaves_it_pending(world):
    records, saves, _, clock = world
    await _queued_wins(records, saves, count=1)

    with pytest.raises(RuntimeError):
        async with get_session_factory()() as session, session.begin():
            await records._repo.claim_event(session, clock.now())
            raise RuntimeError("process died")

    [event] = await _rows(MatchEventRow, MatchEventRow.npid == ALICE)
    assert event.status == "pending"
    assert await records.process_next() is True


async def test_a_failed_event_waits_for_its_retry(world, monkeypatch):
    records, saves, history, clock = world
    await _queued_wins(records, saves, count=1)
    monkeypatch.setattr(history, "rank_room", AsyncMock(side_effect=RuntimeError("hiccup")))

    assert await records.process_next() is True

    [event] = await _rows(MatchEventRow, MatchEventRow.npid == ALICE)
    assert (event.status, event.attempts, event.last_error) == ("pending", 1, "hiccup")
    assert event.available_at > clock.now()
    assert await records.process_next() is False
    assert await _matches() == []


async def test_a_failed_attempt_leaves_no_partial_result(world, monkeypatch):
    records, saves, history, _ = world
    await _open_room(history)
    await _queued_wins(records, saves, count=1)
    monkeypatch.setattr(records._repo, "finish_event", AsyncMock(side_effect=RuntimeError("hiccup")))

    await records.process_next()

    assert await _matches() == []


async def test_an_event_is_buried_after_its_last_attempt(world, monkeypatch):
    records, saves, history, clock = world
    await _queued_wins(records, saves, count=1)
    monkeypatch.setattr(history, "rank_room", AsyncMock(side_effect=RuntimeError("hiccup")))

    for _ in range(5):
        clock.at += timedelta(hours=1)
        await records.process_next()

    [event] = await _rows(MatchEventRow, MatchEventRow.npid == ALICE)
    assert (event.status, event.attempts) == ("dead", 5)
    clock.at += timedelta(hours=1)
    assert await records.process_next() is False


# --- who played whom ------------------------------------------------------------


def _at(minutes: int, seconds: int = 0) -> datetime:
    return _START + timedelta(minutes=minutes, seconds=seconds)


async def test_both_players_of_a_match_share_its_row(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)))
    await _capture(records, saves, _save(BOB, 4, losses=1, at=_at(3, 4)))

    await _drain(records)

    [match] = await _matches()
    [alice] = await _rows(MatchEventRow, MatchEventRow.npid == ALICE)
    [bob] = await _rows(MatchEventRow, MatchEventRow.npid == BOB)
    assert (match.p1_npid, match.p2_npid, match.winner) == (ALICE, BOB, 1)
    assert (match.p1_event_id, match.p2_event_id, match.played_at) == (alice.id, bob.id, _at(3))


async def test_every_match_in_a_reused_room_is_a_row_of_its_own(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    games = [
        (_save(ALICE, 3, wins=1, at=_at(3)), _save(BOB, 4, losses=1, at=_at(3, 4))),
        (_save(ALICE, 5, wins=1, losses=1, at=_at(6)), _save(BOB, 6, wins=1, losses=1, at=_at(6, 2))),
        (_save(ALICE, 7, wins=2, losses=1, at=_at(9, 5)), _save(BOB, 8, wins=1, losses=2, at=_at(9))),
    ]
    for alice, bob in games:
        await _capture(records, saves, alice, bob)

    await _drain(records)

    assert [_shape(match) for match in await _matches()] == [
        (ALICE, BOB, 1, True, True),
        (ALICE, BOB, 2, True, True),
        (ALICE, BOB, 1, True, True),
    ]


async def test_a_quitter_s_side_stays_unseen(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1))
    await _capture(records, saves, _save(ALICE, 2, wins=1, at=_at(3)))

    await _drain(records)

    assert [_shape(match) for match in await _matches()] == [(ALICE, BOB, 1, True, False)]


async def test_a_save_that_comes_late_fills_its_side_of_the_match(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)))
    await _drain(records)

    await _capture(records, saves, _save(BOB, 4, losses=1, at=_at(3, 30)))
    await _drain(records)

    assert [_shape(match) for match in await _matches()] == [(ALICE, BOB, 1, True, True)]


async def test_a_match_outside_any_room_puts_its_player_on_1p_and_keeps_a_loss(world):
    records, saves, _, _ = world
    await _capture(records, saves, _save(ALICE, 1))
    await _capture(records, saves, _save(ALICE, 2, losses=1, at=_at(3)))

    await _drain(records)

    [match] = await _matches()
    assert _shape(match) == (ALICE, None, 2, True, False)
    assert match.room_snapshot_id is None


async def test_two_wins_are_two_matches(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)), _save(BOB, 4, wins=1, at=_at(3)))

    await _drain(records)

    assert [_shape(match) for match in await _matches()] == [(ALICE, BOB, 1, True, False), (ALICE, BOB, 2, False, True)]


async def test_saves_too_far_apart_are_two_matches(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)))
    await _capture(records, saves, _save(BOB, 4, losses=1, at=_at(5)))

    await _drain(records)

    assert [_shape(match) for match in await _matches()] == [(ALICE, BOB, 1, True, False), (ALICE, BOB, 1, False, True)]


async def test_two_consumers_at_once_still_record_one_match(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)), _save(BOB, 4, losses=1, at=_at(3)))

    await asyncio.gather(records.process_next(), records.process_next())

    assert [_shape(match) for match in await _matches()] == [(ALICE, BOB, 1, True, True)]


# --- ranks ----------------------------------------------------------------------


async def test_a_match_keeps_the_rank_each_character_went_in_at(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1, rank=20))
    await _capture(records, saves, _save(ALICE, 2, wins=1, at=_at(3), rank=21))

    await _drain(records)

    [event] = await _rows(MatchEventRow, MatchEventRow.npid == ALICE)
    [match] = (await records.list_matches(ALICE, None, None, 20)).matches
    assert event.ranks == [20]
    assert match.p1.chars[0].rank.name == TEKKEN_RANKS[20]["name"]


# --- reading --------------------------------------------------------------------

_PAUL, _JIN, _LAW = 0, 9, 1


async def _played_match(records, saves, history):
    """Alice (Paul, Berserker) beats Bob (Jin and Law, Marauder), both sides seen."""
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1, chars=(_PAUL,)), _save(BOB, 2, chars=(_JIN, _LAW), rank=18))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3), chars=(_PAUL,)))
    await _capture(records, saves, _save(BOB, 4, losses=1, at=_at(3, 4), chars=(_JIN, _LAW), rank=18))
    await _drain(records)


def _side(side):
    """(npid, name, result, [(character, rank)]) — characters None when that save was not seen."""
    if side is None:
        return None
    chars = None if side.chars is None else [(char.name, char.rank and char.rank.name) for char in side.chars]
    return side.npid, side.online_name, side.result, chars


async def test_a_match_seen_from_both_sides_is_listed_once(world):
    records, saves, history, _ = world
    await _played_match(records, saves, history)

    page = await records.list_matches(None, "records-", None, 20)

    [match] = page.matches
    assert _side(match.p1) == (ALICE, ALICE, "win", [("Paul", "Berserker")])
    assert _side(match.p2) == (BOB, BOB, "loss", [("Law", "Marauder"), ("Jin", "Marauder")])
    assert page.next_before is None


async def test_1p_is_the_room_s_first_member_even_when_they_lost(world):
    records, saves, history, _ = world
    await _open_room(history, npid1=BOB, npid2=ALICE)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)))
    await _capture(records, saves, _save(BOB, 4, losses=1, at=_at(3, 4)))
    await _drain(records)

    [match] = (await records.list_matches(None, "records-", None, 20)).matches

    assert (match.p1.npid, match.p1.result, match.p2.npid, match.p2.result) == (BOB, "loss", ALICE, "win")


async def test_a_quitter_is_listed_without_characters_and_a_roomless_match_without_an_opponent(world):
    records, saves, history, _ = world
    await _open_room(history, until=_at(5))
    await _capture(records, saves, _save(ALICE, 1), _save(CAROL, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)))
    await _capture(records, saves, _save(CAROL, 4, losses=1, at=_at(40)))
    await _drain(records)

    roomless, quitter = (await records.list_matches(None, "records-", None, 20)).matches

    assert _side(quitter.p2) == (BOB, BOB, "loss", None)
    assert (roomless.p1.npid, roomless.p1.result, roomless.p2) == (CAROL, "loss", None)


async def test_a_player_s_matches_include_those_only_the_opponent_s_save_showed(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1))
    await _capture(records, saves, _save(ALICE, 2, wins=1, at=_at(3)))
    await _drain(records)

    [match] = (await records.list_matches(BOB, None, None, 20)).matches

    assert (match.p1.npid, match.p2.npid) == (ALICE, BOB)
    assert (await records.list_matches(CAROL, None, None, 20)).matches == []


async def test_a_search_matches_a_name_in_part_and_takes_wildcards_literally(world):
    records, saves, history, _ = world
    await _played_match(records, saves, history)

    assert len((await records.list_matches(None, "RECORDS-BO", None, 20)).matches) == 1
    assert (await records.list_matches(None, "records-%", None, 20)).matches == []


async def test_pages_follow_on_from_the_last_match_shown(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1))
    for game in range(3):
        await _capture(records, saves, _save(ALICE, 2 + game, wins=game + 1, at=_at(3 * (game + 1))))
    await _drain(records)

    first = await records.list_matches(ALICE, None, None, 2)
    second = await records.list_matches(ALICE, None, first.next_before, 2)

    assert len(first.matches) == 2 and first.next_before == first.matches[-1].id
    assert len(second.matches) == 1 and second.next_before is None
    assert second.matches[0].id < first.matches[-1].id


# --- weekly top -----------------------------------------------------------------


async def _weekly(since=_START, limit=10, excluded=()):
    """(npid, name, matches, wins, losses) per player, read straight from the adapter past the cache."""
    async with get_session_factory()() as session:
        top = await PostgresRecordsAdapter().weekly_top_players(session, since, limit, excluded)
    return [(p.npid, p.online_name, p.match_count, p.wins, p.losses) for p in top]


async def test_weekly_top_counts_every_match_in_a_reused_room(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)), _save(BOB, 4, losses=1, at=_at(3, 4)))
    await _capture(
        records, saves, _save(ALICE, 5, wins=1, losses=1, at=_at(6)), _save(BOB, 6, wins=1, losses=1, at=_at(6, 2))
    )
    await _capture(
        records, saves, _save(ALICE, 7, wins=2, losses=1, at=_at(9)), _save(BOB, 8, wins=1, losses=2, at=_at(9, 3))
    )
    await _drain(records)

    assert await _weekly() == [(ALICE, ALICE, 3, 2, 1), (BOB, BOB, 3, 1, 2)]


async def test_weekly_top_leaves_out_matches_before_its_window(world):
    records, saves, history, _ = world
    await _played_match(records, saves, history)

    assert await _weekly(since=_at(4)) == []


async def test_weekly_top_skips_excluded_npids_before_the_limit(world):
    """Matched case-insensitively, as RPCN usernames are."""
    records, saves, history, _ = world
    await _played_match(records, saves, history)

    assert await _weekly(limit=1, excluded=[ALICE.upper()]) == [(BOB, BOB, 1, 0, 1)]


# --- frequent opponents ---------------------------------------------------------


async def _opponents(npid, since=_START, limit=4):
    """(npid, name, matches, wins, losses) per opponent, read straight from the adapter past the cache."""
    async with get_session_factory()() as session:
        found = await PostgresRecordsAdapter().frequent_opponents(session, npid, since, limit)
    return [(o.npid, o.online_name, o.match_count, o.wins, o.losses) for o in found]


async def test_frequent_opponents_count_every_match_in_a_reused_room_once(world):
    records, saves, history, _ = world
    await _open_room(history)
    await _capture(records, saves, _save(ALICE, 1), _save(BOB, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)), _save(BOB, 4, losses=1, at=_at(3, 4)))
    await _capture(
        records, saves, _save(ALICE, 5, wins=1, losses=1, at=_at(6)), _save(BOB, 6, wins=1, losses=1, at=_at(6, 2))
    )
    await _capture(
        records, saves, _save(ALICE, 7, wins=2, losses=1, at=_at(9)), _save(BOB, 8, wins=1, losses=2, at=_at(9, 3))
    )
    await _drain(records)

    assert await _opponents(ALICE) == [(BOB, BOB, 3, 2, 1)]
    assert await _opponents(BOB) == [(ALICE, ALICE, 3, 1, 2)]


async def test_both_tallies_count_a_match_only_for_a_player_whose_own_save_showed_it(world):
    """Bob quits Alice's match, and Carol's has no room: only Alice's win counts, in both."""
    records, saves, history, _ = world
    await _open_room(history, until=_at(5))
    await _capture(records, saves, _save(ALICE, 1), _save(CAROL, 2))
    await _capture(records, saves, _save(ALICE, 3, wins=1, at=_at(3)))
    await _capture(records, saves, _save(CAROL, 4, losses=1, at=_at(40)))
    await _drain(records)

    assert await _weekly() == [(ALICE, ALICE, 1, 1, 0)]
    assert await _opponents(ALICE) == [(BOB, BOB, 1, 1, 0)]
    assert await _opponents(BOB) == []
    assert await _opponents(CAROL) == []


async def test_frequent_opponents_leave_out_matches_before_their_window(world):
    records, saves, history, _ = world
    await _played_match(records, saves, history)

    assert await _opponents(ALICE, since=_at(4)) == []


async def test_frequent_opponents_put_the_most_met_first_and_stop_at_the_limit(world):
    records, saves, history, _ = world
    await _open_room(history, until=_at(10))
    carol_room = RankMatchSnapshotRecord(_ROOM_ID + 1, 10, ALICE, ALICE, CAROL, CAROL, _at(20))
    await history.record_snapshot([carol_room])
    await history.touch_rank_matches([carol_room], _at(40))
    await _capture(records, saves, _save(ALICE, 1))
    await _capture(records, saves, _save(ALICE, 2, wins=1, at=_at(3)))
    await _capture(records, saves, _save(ALICE, 3, wins=2, at=_at(6)))
    await _capture(records, saves, _save(ALICE, 4, wins=2, losses=1, at=_at(25)))
    await _drain(records)

    assert await _opponents(ALICE) == [(BOB, BOB, 2, 2, 0), (CAROL, CAROL, 1, 0, 1)]
    assert await _opponents(ALICE, limit=1) == [(BOB, BOB, 2, 2, 0)]
