"""Reservation use cases depend only on repository, clock, and credentials ports."""

from datetime import datetime, time

from shared.security.credentials import CredentialManager, TokenCredentialManager, hash_credential
from reservation.domain import MatchType, Reservation, ensure_conditions_valid, start_at_from
from reservation.ports import Clock, ReservationRepository

_repo: ReservationRepository | None = None
class SystemClock(Clock):
    def now(self) -> datetime:
        from datetime import timezone
        return datetime.now(timezone.utc)


_clock: Clock = SystemClock()
_credentials: CredentialManager = TokenCredentialManager()


def configure(repository: ReservationRepository, clock: Clock | None = None, credentials: CredentialManager | None = None) -> None:
    global _repo, _clock, _credentials
    _repo = repository
    if clock is not None: _clock = clock
    if credentials is not None: _credentials = credentials


def _repository() -> ReservationRepository:
    if _repo is None: raise RuntimeError("Reservation repository not initialized")
    return _repo


async def list_reservations() -> list[Reservation]:
    return await _repository().list_upcoming()


async def create_reservation(*, start_time: time, display_name: str, ranks: list[str], match_type: MatchType, capacity: int, memo: str) -> tuple[Reservation, str]:
    ensure_conditions_valid(match_type, ranks, capacity)
    start_at = start_at_from(start_time, _clock.now())
    token, token_hash = _credentials.issue()
    reservation = await _repository().create(start_at=start_at, host_display_name=display_name.strip(), host_ranks=ranks, match_type=match_type, capacity=capacity, memo=memo.strip(), host_token_hash=token_hash)
    return reservation, token


async def get_reservation(reservation_id: int) -> Reservation:
    return await _repository().get(reservation_id)


async def update_reservation(reservation_id: int, token: str, *, start_time: time | None = None, ranks: list[str] | None = None, match_type: MatchType | None = None, capacity: int | None = None, memo: str | None = None) -> Reservation:
    """Apply a partial edit, validating the reservation as it will end up.

    A patch is only coherent against the rest of the reservation: switching to a
    player match while leaving the old ranks in place would pass field-level
    validation and still produce a state the domain forbids. The current values
    are therefore merged in before the conditions are checked.
    """
    current = await _repository().get(reservation_id)
    ensure_conditions_valid(
        match_type if match_type is not None else current.match_type,
        ranks if ranks is not None else current.host_ranks,
        capacity if capacity is not None else current.capacity,
    )
    start_at = start_at_from(start_time, _clock.now()) if start_time is not None else None
    return await _repository().update(
        reservation_id, hash_credential(token), _clock.now(),
        start_at=start_at, ranks=ranks,
        match_type=match_type, capacity=capacity, memo=memo.strip() if memo is not None else None,
    )


async def join_reservation(reservation_id: int, *, display_name: str, ranks: list[str]) -> tuple[Reservation, str]:
    token, token_hash = _credentials.issue()
    reservation, _ = await _repository().join(reservation_id, display_name=display_name.strip(), ranks=ranks, participant_token_hash=token_hash, now=_clock.now())
    return reservation, token


async def cancel_participation(reservation_id: int, token: str) -> Reservation:
    return await _repository().cancel_participation(reservation_id, hash_credential(token), _clock.now())


async def cancel_reservation(reservation_id: int, token: str) -> None:
    await _repository().cancel(reservation_id, hash_credential(token), _clock.now())
