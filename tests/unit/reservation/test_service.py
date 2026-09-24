from datetime import datetime, time, timezone

import pytest

from reservation.domain import MatchType, Reservation, ReservationStatus
from reservation.exceptions import ReservationStateError
from reservation import service


class FixedClock:
    def now(self): return datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self):
        self.created = None
        self.joined = None
        self.cancelled_participation = None
        self.cancelled = None
        self.updated = None
        self.existing = Reservation(1, datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc), "Host", ["Yaksa"], MatchType.RANK, 1, "", ReservationStatus.OPEN, 0, datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc))
    async def create(self, **values):
        self.created = values
        return Reservation(1, values["start_at"], values["host_display_name"], values["host_ranks"], values["match_type"], values["capacity"], values["memo"], ReservationStatus.OPEN, 0, values["start_at"])
    async def join(self, reservation_id, **values):
        self.joined = (reservation_id, values)
        return Reservation(reservation_id, datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc), "Host", [], MatchType.PLAYER, 2, "", ReservationStatus.OPEN, 1, datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)), None
    async def cancel_participation(self, reservation_id, subject, now):
        self.cancelled_participation = (reservation_id, subject, now)
        return Reservation(reservation_id, now, "Host", [], MatchType.RANK, 1, "", ReservationStatus.OPEN, 0, now)
    async def cancel(self, reservation_id, subject, now):
        self.cancelled = (reservation_id, subject, now)
    async def get(self, reservation_id):
        return self.existing
    async def update(self, reservation_id, subject, now, **changes):
        self.updated = (reservation_id, subject, changes)
        return self.existing


@pytest.fixture(autouse=True)
def dependencies():
    """Swap the module-level ports for fakes, then put the real ones back.

    service.configure() writes to module globals, so a fake clock left behind
    here would still be answering when the integration tests run.
    """
    previous = (service._repo, service._clock)
    repo = FakeRepository()
    service.configure(repo, FixedClock())
    yield repo
    service._repo, service._clock = previous


@pytest.mark.asyncio
async def test_create_rank_reservation_uses_kst_today_and_records_the_host(dependencies):
    reservation = await service.create_reservation(subject="host", display_name="Host", start_time=time(20, 30), ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="hello")

    assert reservation.host_display_name == "Host"
    assert dependencies.created["host_subject"] == "host"
    assert dependencies.created["start_at"].hour == 11  # 20:30 KST in UTC


@pytest.mark.asyncio
async def test_create_rank_reservation_requires_rank(dependencies):
    with pytest.raises(ReservationStateError, match="계급을 하나 이상"):
        await service.create_reservation(start_time=time(20, 30), subject="host", display_name="Host", ranks=[], match_type=MatchType.RANK, capacity=1, memo="")


@pytest.mark.asyncio
async def test_create_player_reservation_rejects_ranks(dependencies):
    with pytest.raises(ReservationStateError, match="계급을 선택하지 않습니다"):
        await service.create_reservation(start_time=time(20, 30), subject="host", display_name="Host", ranks=["Brawler"], match_type=MatchType.PLAYER, capacity=2, memo="")


@pytest.mark.asyncio
async def test_create_rejects_start_time_less_than_ten_minutes_away(dependencies):
    with pytest.raises(ReservationStateError, match="10분 이후"):
        await service.create_reservation(start_time=time(19, 5), subject="host", display_name="Host", ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="")


@pytest.mark.asyncio
async def test_create_rank_reservation_rejects_capacity_other_than_one(dependencies):
    with pytest.raises(ReservationStateError, match="1명만 모집"):
        await service.create_reservation(start_time=time(20, 30), subject="host", display_name="Host", ranks=["Brawler"], match_type=MatchType.RANK, capacity=2, memo="")


@pytest.mark.asyncio
async def test_join_passes_the_account_to_the_repository(dependencies):
    await service.join_reservation(12, subject="joiner", display_name="Joiner", ranks=[])

    reservation_id, values = dependencies.joined
    assert reservation_id == 12
    assert values["subject"] == "joiner"
    assert values["display_name"] == "Joiner"


@pytest.mark.asyncio
async def test_cancellations_name_the_account_that_asked(dependencies):
    await service.cancel_participation(12, "joiner")
    await service.cancel_reservation(12, "host")

    assert dependencies.cancelled_participation[1] == "joiner"
    assert dependencies.cancelled[1] == "host"


@pytest.mark.asyncio
async def test_editing_only_the_memo_leaves_the_other_fields_untouched(dependencies):
    await service.update_reservation(1, "host", memo="  자리 하나 남음  ")

    _, _, changes = dependencies.updated
    assert changes["memo"] == "자리 하나 남음"
    assert changes["start_at"] is None
    assert changes["match_type"] is None


@pytest.mark.asyncio
async def test_switching_to_a_player_match_rejects_the_ranks_left_behind():
    """The patch is valid field by field; only the merged state reveals the clash."""
    with pytest.raises(ReservationStateError, match="계급을 선택하지 않습니다"):
        await service.update_reservation(1, "host", match_type=MatchType.PLAYER)


@pytest.mark.asyncio
async def test_switching_to_a_player_match_together_with_clearing_ranks_is_allowed(dependencies):
    await service.update_reservation(1, "host", match_type=MatchType.PLAYER, ranks=[], capacity=2)

    _, _, changes = dependencies.updated
    assert changes["match_type"] is MatchType.PLAYER
    assert changes["ranks"] == []


@pytest.mark.asyncio
async def test_emptying_the_ranks_of_a_rank_match_is_rejected():
    with pytest.raises(ReservationStateError, match="하나 이상"):
        await service.update_reservation(1, "host", ranks=[])


@pytest.mark.asyncio
async def test_a_new_start_time_is_resolved_against_the_clock(dependencies):
    await service.update_reservation(1, "host", start_time=time(21, 0))

    _, _, changes = dependencies.updated
    assert changes["start_at"] == datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_start_time_inside_the_lead_time_is_rejected():
    with pytest.raises(ReservationStateError, match="10분 이후"):
        await service.update_reservation(1, "host", start_time=time(19, 5))


@pytest.mark.asyncio
async def test_the_editor_reaches_the_repository(dependencies):
    await service.update_reservation(1, "host", memo="hi")

    _, subject, _ = dependencies.updated
    assert subject == "host"
