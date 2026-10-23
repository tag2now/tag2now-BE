"""Reservation use cases, depending only on the repository and clock ports.

Every write names its actor by `subject` (the RPCN username) and
`display_name` (what the listing shows). Ownership compares subjects; the
router takes both from the signed-in user, never from the request body.
"""

from datetime import time

from reservation.domain import Comment, MatchType, Reservation, ensure_conditions_valid, start_at_from
from reservation.ports import ReservationRepository
from shared.clock import Clock, SystemClock


class ReservationService:
    def __init__(self, repo: ReservationRepository, clock: Clock | None = None):
        self._repo = repo
        self._clock = clock or SystemClock()

    async def list_reservations(self) -> list[Reservation]:
        return await self._repo.list_upcoming()

    async def create_reservation(self, *, subject: str, display_name: str, start_time: time, ranks: list[str], match_type: MatchType, capacity: int, memo: str) -> Reservation:
        ensure_conditions_valid(match_type, ranks, capacity)
        start_at = start_at_from(start_time, self._clock.now())
        return await self._repo.create(start_at=start_at, host_subject=subject, host_display_name=display_name, host_ranks=ranks, match_type=match_type, capacity=capacity, memo=memo.strip())

    async def get_reservation(self, reservation_id: int) -> Reservation:
        return await self._repo.get(reservation_id)

    async def update_reservation(self, reservation_id: int, subject: str, *, start_time: time | None = None, ranks: list[str] | None = None, match_type: MatchType | None = None, capacity: int | None = None, memo: str | None = None) -> Reservation:
        """Apply a partial edit, validating the reservation as it will end up.

        A patch is only coherent against the rest of the reservation: switching to a
        player match while leaving the old ranks in place would pass field-level
        validation and still produce a state the domain forbids. The current values
        are therefore merged in before the conditions are checked.
        """
        current = await self._repo.get(reservation_id)
        ensure_conditions_valid(
            match_type if match_type is not None else current.match_type,
            ranks if ranks is not None else current.host_ranks,
            capacity if capacity is not None else current.capacity,
        )
        start_at = start_at_from(start_time, self._clock.now()) if start_time is not None else None
        return await self._repo.update(
            reservation_id, subject, self._clock.now(),
            start_at=start_at, ranks=ranks,
            match_type=match_type, capacity=capacity, memo=memo.strip() if memo is not None else None,
        )

    async def join_reservation(self, reservation_id: int, *, subject: str, display_name: str, ranks: list[str]) -> Reservation:
        reservation, _ = await self._repo.join(reservation_id, subject=subject, display_name=display_name, ranks=ranks, now=self._clock.now())
        return reservation

    async def cancel_participation(self, reservation_id: int, subject: str) -> Reservation:
        return await self._repo.cancel_participation(reservation_id, subject, self._clock.now())

    async def list_comments(self, reservation_id: int) -> list[Comment]:
        return await self._repo.list_comments(reservation_id)

    async def add_comment(self, reservation_id: int, *, subject: str, display_name: str, body: str) -> Comment:
        return await self._repo.add_comment(reservation_id, author_subject=subject, author=display_name, body=body.strip())

    async def delete_comment(self, reservation_id: int, comment_id: int, subject: str) -> None:
        await self._repo.delete_comment(reservation_id, comment_id, subject, self._clock.now())

    async def cancel_reservation(self, reservation_id: int, subject: str) -> None:
        await self._repo.cancel(reservation_id, subject, self._clock.now())
