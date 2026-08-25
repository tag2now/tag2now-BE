"""PostgreSQL reservation tests. Requires the test compose stack to be running."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from reservation.domain import MatchType, ReservationStatus
from reservation.entities import Reservation as ReservationRow
from reservation.entities import ReservationParticipant as ReservationParticipantRow
from reservation.exceptions import ReservationStateError
from shared.database import close_database, get_session_factory, init_database


@pytest_asyncio.fixture
async def repository():
    from reservation.adapters.postgresql import PostgresReservationRepository

    await init_database()
    repo = PostgresReservationRepository()
    await repo.init()
    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(ReservationParticipantRow))
        await session.execute(delete(ReservationRow))
    yield repo
    await repo.close()
    await close_database()


async def _create_open_reservation(repo, capacity: int = 1):
    return await repo.create(
        start_at=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_minutes=60,
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
        start_at=past, duration_minutes=60, host_display_name="Host", host_ranks=["Brawler"],
        match_type=MatchType.RANK, capacity=1, memo="", host_token_hash="owner",
    )
    await repository.join(reservation.id, display_name="Joiner", ranks=[], participant_token_hash="participant", now=past - timedelta(minutes=1))

    await repository.list_for_date(past.date())

    assert (await repository.get(reservation.id)).status is ReservationStatus.ENDED
    assert await _active_participant_count(reservation.id) == 0
