"""PostgreSQL reservation tests. Requires the test compose stack to be running."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, func, select
from sqlalchemy.engine import Engine

from reservation.domain import LISTING_GRACE, MatchType, ReservationStatus, window_end
from reservation.entities import Reservation as ReservationRow
from reservation.entities import ReservationComment as ReservationCommentRow
from reservation.entities import ReservationParticipant as ReservationParticipantRow
from reservation.exceptions import ReservationAccessError, ReservationNotFoundError, ReservationStateError
from shared.database import close_database, get_session_factory, init_database


@pytest_asyncio.fixture
async def repository():
    from reservation.adapters.postgresql import PostgresReservationRepository

    await init_database()
    repo = PostgresReservationRepository()
    await repo.init()
    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(ReservationCommentRow))
        await session.execute(delete(ReservationParticipantRow))
        await session.execute(delete(ReservationRow))
    yield repo
    await repo.close()
    await close_database()


async def _create_open_reservation(repo, capacity: int = 1):
    return await repo.create(
        start_at=datetime.now(timezone.utc) + timedelta(hours=1),
        host_display_name="Host",
        host_ranks=["Brawler"],
        match_type=MatchType.RANK if capacity == 1 else MatchType.PLAYER,
        capacity=capacity,
        memo="",
        host_token_hash="owner",
    )


@pytest.mark.asyncio
async def test_concurrent_join_never_exceeds_capacity(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)

    async def join(token):
        return await repository.join(reservation.id, display_name=token, ranks=[], participant_token_hash=token, now=now)

    outcomes = await asyncio.gather(join("participant-a"), join("participant-b"), return_exceptions=True)

    successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ReservationStateError)
    current = await repository.get(reservation.id)
    assert current.participant_count == 1
    assert current.status is ReservationStatus.MATCHED


@pytest.mark.asyncio
async def test_participant_cancellation_reopens_a_matched_reservation(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)
    await repository.join(reservation.id, display_name="Joiner", ranks=[], participant_token_hash="participant", now=now)

    reopened = await repository.cancel_participation(reservation.id, "participant", now)

    assert reopened.status is ReservationStatus.OPEN
    assert reopened.participant_count == 0


@pytest.mark.asyncio
async def test_participant_cancellation_does_not_revive_a_cancelled_reservation(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)
    await repository.join(reservation.id, display_name="Joiner", ranks=[], participant_token_hash="participant", now=now)
    await repository.cancel(reservation.id, "owner", now)

    with pytest.raises(ReservationStateError):
        await repository.cancel_participation(reservation.id, "participant", now)

    current = await repository.get(reservation.id)
    assert current.status is ReservationStatus.CANCELLED


async def _active_participant_count(reservation_id: int) -> int:
    async with get_session_factory()() as session:
        return await session.scalar(
            select(func.count()).select_from(ReservationParticipantRow).where(
                ReservationParticipantRow.reservation_id == reservation_id,
                ReservationParticipantRow.cancelled_at.is_(None),
            )
        )


@pytest.mark.asyncio
async def test_cancelling_a_reservation_also_releases_its_participants(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)
    await repository.join(reservation.id, display_name="Joiner", ranks=[], participant_token_hash="participant", now=now)

    await repository.cancel(reservation.id, "owner", now)

    assert await _active_participant_count(reservation.id) == 0


@pytest.mark.asyncio
async def test_expiring_a_reservation_also_releases_its_participants(repository):
    past = datetime.now(timezone.utc) - timedelta(hours=3)
    reservation = await repository.create(
        start_at=past, host_display_name="Host", host_ranks=["Brawler"],
        match_type=MatchType.RANK, capacity=1, memo="", host_token_hash="owner",
    )
    await repository.join(reservation.id, display_name="Joiner", ranks=[], participant_token_hash="participant", now=past - timedelta(minutes=1))

    await repository.list_upcoming()

    assert (await repository.get(reservation.id)).status is ReservationStatus.ENDED
    assert await _active_participant_count(reservation.id) == 0


async def _expired_reservation(repo, token: str):
    past = datetime.now(timezone.utc) - timedelta(hours=3)
    reservation = await repo.create(
        start_at=past, host_display_name="Host", host_ranks=["Brawler"],
        match_type=MatchType.RANK, capacity=1, memo="", host_token_hash=token,
    )
    await repo.join(reservation.id, display_name="Joiner", ranks=[], participant_token_hash=token, now=past - timedelta(minutes=1))
    return reservation


@pytest.mark.asyncio
async def test_the_expiry_sweep_costs_the_same_no_matter_how_many_expired(repository):
    """Cost must not grow with the table: the sweep is two statements, always."""
    def updates_during_listing():
        statements = []

        def record(conn, cursor, statement, *_):
            if statement.lstrip().upper().startswith("UPDATE"):
                statements.append(statement)

        async def run():
            event.listen(Engine, "before_cursor_execute", record)
            try:
                await repository.list_upcoming()
            finally:
                event.remove(Engine, "before_cursor_execute", record)
            return statements

        return run()

    await _expired_reservation(repository, "owner-1")
    assert len(await updates_during_listing()) == 2

    for index in range(2, 6):
        await _expired_reservation(repository, f"owner-{index}")
    assert len(await updates_during_listing()) == 2


@pytest.mark.asyncio
async def test_the_sweep_expires_reservations_outside_the_listed_window(repository):
    """A stale reservation is retired even though the listing never returns it."""
    old = await _expired_reservation(repository, "owner")

    assert old.id not in [item.id for item in await repository.list_upcoming()]

    assert (await repository.get(old.id)).status is ReservationStatus.ENDED
    assert await _active_participant_count(old.id) == 0


@pytest.mark.asyncio
async def test_the_listing_covers_the_grace_hour_until_the_next_dawn(repository):
    """The window trails an hour behind now and stops at the next 06:00 KST.

    A reservation under way is still the players' own — and the listing is the
    only way to reach its detail page — so it stays until the grace hour is up.
    """
    now = datetime.now(timezone.utc)
    upcoming = await _create_open_reservation(repository)
    running = await repository.create(
        start_at=now - timedelta(minutes=5), host_display_name="Host",
        host_ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="", host_token_hash="running",
    )
    long_over = await repository.create(
        start_at=now - LISTING_GRACE - timedelta(minutes=1), host_display_name="Host",
        host_ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="", host_token_hash="over",
    )
    beyond = await repository.create(
        start_at=window_end(now) + timedelta(minutes=1), host_display_name="Host",
        host_ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="", host_token_hash="beyond",
    )

    listed = [item.id for item in await repository.list_upcoming()]

    assert upcoming.id in listed
    assert running.id in listed
    assert long_over.id not in listed
    assert beyond.id not in listed


@pytest.mark.asyncio
async def test_a_reservation_is_retired_once_its_grace_hour_runs_out(repository):
    """Expiry and the listing floor are the same instant, so nothing lingers."""
    now = datetime.now(timezone.utc)
    stale = await repository.create(
        start_at=now - LISTING_GRACE - timedelta(minutes=1), host_display_name="Host",
        host_ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="", host_token_hash="stale",
    )

    await repository.list_upcoming()

    assert (await repository.get(stale.id)).status is ReservationStatus.ENDED


@pytest.mark.asyncio
async def test_an_edit_persists_only_the_fields_it_names(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)

    edited = await repository.update(reservation.id, "owner", now, memo="자리 하나 남음")

    assert edited.memo == "자리 하나 남음"
    assert edited.host_ranks == reservation.host_ranks
    assert edited.start_at == reservation.start_at


@pytest.mark.asyncio
async def test_an_edit_can_replace_the_ranks(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)

    edited = await repository.update(reservation.id, "owner", now, ranks=["Yaksa", "Fujin"])

    assert edited.host_ranks == ["Yaksa", "Fujin"]


@pytest.mark.asyncio
async def test_an_edit_can_switch_the_match_type(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)

    edited = await repository.update(reservation.id, "owner", now, match_type=MatchType.PLAYER, ranks=[], capacity=2)

    assert edited.match_type is MatchType.PLAYER
    assert edited.capacity == 2


@pytest.mark.asyncio
async def test_someone_elses_token_cannot_edit_a_reservation(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)

    with pytest.raises(ReservationAccessError):
        await repository.update(reservation.id, "not-the-owner", now, memo="stolen")

    assert (await repository.get(reservation.id)).memo == ""


@pytest.mark.asyncio
async def test_a_reservation_with_a_participant_cannot_be_edited(repository):
    reservation = await _create_open_reservation(repository, capacity=2)
    now = datetime.now(timezone.utc)
    await repository.join(reservation.id, display_name="Joiner", ranks=[], participant_token_hash="participant", now=now)

    with pytest.raises(ReservationStateError, match="참가자가 있는 예약"):
        await repository.update(reservation.id, "owner", now, memo="too late")


@pytest.mark.asyncio
async def test_a_cancelled_reservation_cannot_be_edited(repository):
    reservation = await _create_open_reservation(repository)
    now = datetime.now(timezone.utc)
    await repository.cancel(reservation.id, "owner", now)

    with pytest.raises(ReservationStateError):
        await repository.update(reservation.id, "owner", now, memo="zombie")


@pytest.mark.asyncio
async def test_a_deleted_comment_is_kept_but_stops_being_listed(repository):
    """Soft delete: the listing is ordered by creation and people quote each other."""
    reservation = await _create_open_reservation(repository)
    comment = await repository.add_comment(
        reservation.id, author="Author", body="곧 갑니다", author_token_hash="author",
    )

    await repository.delete_comment(reservation.id, comment.id, "author", datetime.now(timezone.utc))

    assert await repository.list_comments(reservation.id) == []
    async with get_session_factory()() as session:
        assert await session.get(ReservationCommentRow, comment.id) is not None


@pytest.mark.asyncio
async def test_a_comment_id_from_another_reservation_is_not_found(repository):
    """The path names both, so a mismatched pair must not delete anything."""
    mine = await _create_open_reservation(repository)
    theirs = await repository.create(
        start_at=datetime.now(timezone.utc) + timedelta(hours=2), host_display_name="Other",
        host_ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="", host_token_hash="other",
    )
    comment = await repository.add_comment(
        theirs.id, author="Author", body="여기요", author_token_hash="author",
    )

    with pytest.raises(ReservationNotFoundError):
        await repository.delete_comment(mine.id, comment.id, "author", datetime.now(timezone.utc))

    assert [c.id for c in await repository.list_comments(theirs.id)] == [comment.id]


@pytest.mark.asyncio
async def test_cancelling_a_reservation_takes_its_comments_with_it(repository):
    """The rows go with the parent row --- the FK is ON DELETE CASCADE."""
    reservation = await _create_open_reservation(repository)
    await repository.add_comment(
        reservation.id, author="Author", body="갑니다", author_token_hash="author",
    )

    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(ReservationRow).where(ReservationRow.id == reservation.id))

    assert await repository.list_comments(reservation.id) == []
