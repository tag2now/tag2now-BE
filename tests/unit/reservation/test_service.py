from datetime import datetime, time, timezone

import pytest

from shared.security.credentials import hash_credential
from reservation.domain import MatchType, Reservation, ReservationStatus
from reservation.exceptions import ReservationStateError
from reservation import service


class FakeCredentials:
    def __init__(self): self.index = 0
    def issue(self):
        self.index += 1
        token = f"token-{self.index}"
        return token, hash_credential(token)


class FixedClock:
    def now(self): return datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self):
        self.created = None
        self.joined = None
        self.cancelled_participation = None
        self.cancelled = None
        self.updated = None
        self.existing = Reservation(1, datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc), 60, "Host", ["Yaksa"], MatchType.RANK, 1, "", ReservationStatus.OPEN, 0, datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc))
    async def create(self, **values):
        self.created = values
        return Reservation(1, values["start_at"], values["duration_minutes"], values["host_display_name"], values["host_ranks"], values["match_type"], values["capacity"], values["memo"], ReservationStatus.OPEN, 0, values["start_at"])
    async def join(self, reservation_id, **values):
        self.joined = (reservation_id, values)
        return Reservation(reservation_id, datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc), 60, "Host", [], MatchType.PLAYER, 2, "", ReservationStatus.OPEN, 1, datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)), None
    async def cancel_participation(self, reservation_id, token_hash, now):
        self.cancelled_participation = (reservation_id, token_hash, now)
        return Reservation(reservation_id, now, 60, "Host", [], MatchType.RANK, 1, "", ReservationStatus.OPEN, 0, now)
    async def cancel(self, reservation_id, token_hash, now):
        self.cancelled = (reservation_id, token_hash, now)
    async def get(self, reservation_id):
        return self.existing
    async def update(self, reservation_id, token_hash, now, **changes):
        self.updated = (reservation_id, token_hash, changes)
        return self.existing


@pytest.fixture(autouse=True)
def dependencies():
    """Swap the module-level ports for fakes, then put the real ones back.

    service.configure() writes to module globals, so a fake clock left behind
    here would still be answering when the integration tests run.
    """
    previous = (service._repo, service._clock, service._credentials)
    repo = FakeRepository()
    service.configure(repo, FixedClock(), FakeCredentials())
    yield repo
    service._repo, service._clock, service._credentials = previous


@pytest.mark.asyncio
async def test_create_rank_reservation_uses_kst_today_and_issues_owner_token(dependencies):
    reservation, token = await service.create_reservation(start_time=time(20, 30), duration_minutes=60, display_name="Host", ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="hello")

    assert token == "token-1"
    assert reservation.host_display_name == "Host"
    assert dependencies.created["start_at"].hour == 11  # 20:30 KST in UTC


@pytest.mark.asyncio
async def test_create_rank_reservation_requires_rank(dependencies):
    with pytest.raises(ReservationStateError, match="계급을 하나 이상"):
        await service.create_reservation(start_time=time(20, 30), duration_minutes=60, display_name="Host", ranks=[], match_type=MatchType.RANK, capacity=1, memo="")


@pytest.mark.asyncio
async def test_create_player_reservation_rejects_ranks(dependencies):
    with pytest.raises(ReservationStateError, match="계급을 선택하지 않습니다"):
        await service.create_reservation(start_time=time(20, 30), duration_minutes=60, display_name="Host", ranks=["Brawler"], match_type=MatchType.PLAYER, capacity=2, memo="")


@pytest.mark.asyncio
async def test_create_rejects_start_time_less_than_ten_minutes_away(dependencies):
    with pytest.raises(ReservationStateError, match="10분 이후"):
        await service.create_reservation(start_time=time(19, 5), duration_minutes=60, display_name="Host", ranks=["Brawler"], match_type=MatchType.RANK, capacity=1, memo="")


@pytest.mark.asyncio
async def test_create_rank_reservation_rejects_capacity_other_than_one(dependencies):
    with pytest.raises(ReservationStateError, match="1명만 모집"):
        await service.create_reservation(start_time=time(20, 30), duration_minutes=60, display_name="Host", ranks=["Brawler"], match_type=MatchType.RANK, capacity=2, memo="")


@pytest.mark.asyncio
async def test_join_issues_a_participant_token_and_never_passes_it_raw(dependencies):
    _, token = await service.join_reservation(12, display_name="Joiner", ranks=[])

    reservation_id, values = dependencies.joined
    assert token == "token-1"
    assert reservation_id == 12
    assert values["participant_token_hash"] == hash_credential(token)
    assert values["participant_token_hash"] != token


@pytest.mark.asyncio
async def test_cancellation_hashes_client_tokens_before_repository_access(dependencies):
    await service.cancel_participation(12, "participant-token")
    await service.cancel_reservation(12, "owner-token")

    assert dependencies.cancelled_participation[1] == hash_credential("participant-token")
    assert dependencies.cancelled[1] == hash_credential("owner-token")


@pytest.mark.asyncio
async def test_editing_only_the_memo_leaves_the_other_fields_untouched(dependencies):
    await service.update_reservation(1, "token-1", memo="  자리 하나 남음  ")

    _, _, changes = dependencies.updated
    assert changes["memo"] == "자리 하나 남음"
    assert changes["start_at"] is None
    assert changes["match_type"] is None


@pytest.mark.asyncio
async def test_switching_to_a_player_match_rejects_the_ranks_left_behind():
    """The patch is valid field by field; only the merged state reveals the clash."""
    with pytest.raises(ReservationStateError, match="계급을 선택하지 않습니다"):
        await service.update_reservation(1, "token-1", match_type=MatchType.PLAYER)


@pytest.mark.asyncio
async def test_switching_to_a_player_match_together_with_clearing_ranks_is_allowed(dependencies):
    await service.update_reservation(1, "token-1", match_type=MatchType.PLAYER, ranks=[], capacity=2)

    _, _, changes = dependencies.updated
    assert changes["match_type"] is MatchType.PLAYER
    assert changes["ranks"] == []


@pytest.mark.asyncio
async def test_emptying_the_ranks_of_a_rank_match_is_rejected():
    with pytest.raises(ReservationStateError, match="하나 이상"):
        await service.update_reservation(1, "token-1", ranks=[])


@pytest.mark.asyncio
async def test_a_new_start_time_is_resolved_against_the_clock(dependencies):
    await service.update_reservation(1, "token-1", start_time=time(21, 0))

    _, _, changes = dependencies.updated
    assert changes["start_at"] == datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_start_time_inside_the_lead_time_is_rejected():
    with pytest.raises(ReservationStateError, match="10분 이후"):
        await service.update_reservation(1, "token-1", start_time=time(19, 5))


@pytest.mark.asyncio
async def test_the_token_reaches_the_repository_hashed(dependencies):
    await service.update_reservation(1, "token-1", memo="hi")

    _, token_hash, _ = dependencies.updated
    assert token_hash == hash_credential("token-1")
