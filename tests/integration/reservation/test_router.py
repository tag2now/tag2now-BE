"""Reservation HTTP contract: what a client actually receives, good request or bad.

Requires the test compose stack to be running.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

KST = ZoneInfo("Asia/Seoul")


def _truncate_reservations():
    import asyncpg
    from shared.database import build_dsn

    async def _run():
        connection = await asyncpg.connect(build_dsn(driver=""))
        try:
            await connection.execute(
                "TRUNCATE reservations, reservation_participants RESTART IDENTITY CASCADE"
            )
        finally:
            await connection.close()

    asyncio.run(_run())


@pytest.fixture()
def client():
    """A client over an empty reservations table, left empty for the next test.

    Listing and capacity assertions count rows, so a leftover row from an
    earlier test would let a broken query pass.
    """
    from app import app

    _truncate_reservations()
    with TestClient(app) as tc:
        yield tc
    _truncate_reservations()


def _window_end() -> datetime:
    """The next 06:00 KST — the far edge of what the API lists and accepts."""
    now = datetime.now(timezone.utc).astimezone(KST)
    end = now.replace(hour=6, minute=0, second=0, microsecond=0)
    return end if now < end else end + timedelta(days=1)


def _bookable_time_of_day() -> str:
    """A time of day past the lead time that still lands before the next dawn.

    The window can be as short as ten minutes just before 06:00, so the offsets
    step down rather than assuming an evening's worth of room.
    """
    now = datetime.now(timezone.utc).astimezone(KST)
    for offset in (timedelta(hours=2), timedelta(minutes=30), timedelta(minutes=11)):
        candidate = now + offset
        if candidate < _window_end():
            return candidate.strftime("%H:%M:%S")
    pytest.skip("the window closes too soon to book anything in it")


def _unbookable_time_of_day() -> str:
    """A time of day the window cannot reach — one hour past the next dawn."""
    return (_window_end() + timedelta(hours=1)).strftime("%H:%M:%S")


def _payload(**overrides):
    body = {
        "start_time": _bookable_time_of_day(),
        "duration_minutes": 60,
        "display_name": "Host",
        "ranks": ["Brawler"],
        "match_type": "rank_match",
        "capacity": 1,
        "memo": "",
    }
    return {**body, **overrides}


def test_a_schema_violation_states_the_rule_that_failed(client):
    response = client.post("/reservations", json=_payload(duration_minutes=45))

    assert response.status_code == 422
    assert response.json() == {"detail": "예상 시간은 30분, 60분, 120분, 180분 중에서 선택해 주세요."}


def test_one_rule_is_answered_even_when_several_fields_fail(client):
    """A form shows one line, so the first violation that names a rule wins.

    Both of these are specific, and pydantic reports them in field order --- the
    point is that neither falls back to naming its field, which used to let the
    vaguer of the two mask the other.
    """
    response = client.post("/reservations", json=_payload(duration_minutes=45, display_name=""))

    assert response.status_code == 422
    assert response.json()["detail"] == "예상 시간은 30분, 60분, 120분, 180분 중에서 선택해 주세요."

    response = client.post("/reservations", json=_payload(display_name=""))

    assert response.status_code == 422
    assert response.json()["detail"] == "유저명을 입력해 주세요."


def test_a_domain_rule_answers_400_with_its_own_message(client):
    response = client.post("/reservations", json=_payload(ranks=[]))

    assert response.status_code == 400
    assert response.json() == {"detail": "랭크매치는 보유 계급을 하나 이상 선택해야 합니다."}


def test_both_failure_kinds_share_one_response_shape(client):
    """Statuses differ by kind, but a client parses one body shape either way."""
    schema = client.post("/reservations", json=_payload(duration_minutes=45))
    domain = client.post("/reservations", json=_payload(ranks=[]))

    assert (schema.status_code, domain.status_code) == (422, 400)
    assert list(schema.json()) == list(domain.json()) == ["detail"]
    assert all(isinstance(r.json()["detail"], str) for r in (schema, domain))


# --- Success paths -----------------------------------------------------------
# The four cases above cover how a bad request comes back. The rest of this file
# covers the other half of the contract: what a client receives when the request
# is good, and whether the domain rules survive the trip through HTTP.


def _create(client, **overrides):
    """Create a reservation over HTTP and hand back (body, owner_token)."""
    response = client.post("/reservations", json=_payload(**overrides))
    assert response.status_code == 201, response.text
    body = response.json()
    return body["reservation"], body["owner_token"]


def _join(client, reservation_id, display_name="Joiner", ranks=()):
    response = client.post(
        f"/reservations/{reservation_id}/participants",
        json={"display_name": display_name, "ranks": list(ranks)},
    )
    return response


def test_creating_a_reservation_answers_the_row_and_an_owner_token(client):
    reservation, owner_token = _create(client)

    assert reservation["status"] == "open"
    assert reservation["participant_count"] == 0
    assert reservation["host_display_name"] == "Host"
    assert reservation["match_type"] == "rank_match"
    assert owner_token


def test_a_match_type_of_any_keeps_both_its_ranks_and_a_larger_capacity(client):
    reservation, _ = _create(client, match_type="any", ranks=["Brawler"], capacity=2)

    assert reservation["match_type"] == "any"
    assert reservation["host_ranks"] == ["Brawler"]
    assert reservation["capacity"] == 2


def test_a_new_reservation_is_listed_without_asking_for_a_date(client):
    reservation, _ = _create(client)

    listed = client.get("/reservations")

    assert listed.status_code == 200
    assert reservation["id"] in [item["id"] for item in listed.json()]


def test_a_time_of_day_past_dawn_is_refused(client):
    """The window ends at 06:00 KST, so nothing can be booked into the day after."""
    response = client.post("/reservations", json=_payload(start_time=_unbookable_time_of_day()))

    assert response.status_code == 400
    assert "오전 6시" in response.json()["detail"]


def test_fetching_one_reservation_returns_the_same_row_the_creation_did(client):
    reservation, _ = _create(client)

    fetched = client.get(f"/reservations/{reservation['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == reservation


def test_fetching_a_reservation_that_never_existed_is_a_404(client):
    response = client.get("/reservations/99999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Reservation not found"}


def test_joining_fills_a_rank_match_and_hands_back_a_participant_token(client):
    reservation, _ = _create(client)

    response = _join(client, reservation["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["participant_token"]
    assert body["reservation"]["status"] == "matched"
    assert body["reservation"]["participant_count"] == 1


def test_joining_a_reservation_that_never_existed_is_a_404(client):
    response = _join(client, 99999999)

    assert response.status_code == 404


def test_joining_past_capacity_is_refused_as_a_domain_violation(client):
    reservation, _ = _create(client)
    _join(client, reservation["id"], display_name="First")

    response = _join(client, reservation["id"], display_name="Second")

    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_a_participant_cancelling_reopens_the_reservation(client):
    reservation, _ = _create(client)
    participant_token = _join(client, reservation["id"]).json()["participant_token"]

    response = client.delete(
        f"/reservations/{reservation['id']}/participants/me",
        headers={"X-Reservation-Token": participant_token},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    assert response.json()["participant_count"] == 0


def test_a_stranger_cannot_cancel_someone_elses_participation(client):
    reservation, owner_token = _create(client)
    _join(client, reservation["id"])

    response = client.delete(
        f"/reservations/{reservation['id']}/participants/me",
        headers={"X-Reservation-Token": owner_token},
    )

    assert response.status_code == 403


def test_cancelling_a_participation_without_the_header_is_refused(client):
    reservation, _ = _create(client)
    _join(client, reservation["id"])

    response = client.delete(f"/reservations/{reservation['id']}/participants/me")

    assert response.status_code == 400


def test_the_host_cancels_the_reservation_and_it_leaves_the_days_list(client):
    reservation, owner_token = _create(client)

    response = client.delete(
        f"/reservations/{reservation['id']}",
        headers={"X-Reservation-Token": owner_token},
    )

    assert response.status_code == 204
    assert client.get(f"/reservations/{reservation['id']}").json()["status"] == "cancelled"
    listed = client.get("/reservations")
    assert reservation["id"] not in [item["id"] for item in listed.json()]


def test_a_participant_token_cannot_cancel_the_whole_reservation(client):
    reservation, _ = _create(client)
    participant_token = _join(client, reservation["id"]).json()["participant_token"]

    response = client.delete(
        f"/reservations/{reservation['id']}",
        headers={"X-Reservation-Token": participant_token},
    )

    assert response.status_code == 403


def test_cancelling_a_reservation_without_the_header_is_refused(client):
    reservation, _ = _create(client)

    response = client.delete(f"/reservations/{reservation['id']}")

    assert response.status_code == 400


def test_editing_a_reservation_answers_the_updated_row(client):
    reservation, owner_token = _create(client)

    response = client.patch(
        f"/reservations/{reservation['id']}",
        json={"memo": "자리 하나 남음"},
        headers={"X-Reservation-Token": owner_token},
    )

    assert response.status_code == 200
    assert response.json()["memo"] == "자리 하나 남음"
    assert response.json()["duration_minutes"] == reservation["duration_minutes"]


def test_editing_without_a_token_is_refused(client):
    reservation, _ = _create(client)

    response = client.patch(f"/reservations/{reservation['id']}", json={"memo": "x"})

    assert response.status_code == 400


def test_editing_with_someone_elses_token_is_forbidden(client):
    reservation, _ = _create(client)
    _, other_token = _create(client)

    response = client.patch(
        f"/reservations/{reservation['id']}",
        json={"memo": "stolen"},
        headers={"X-Reservation-Token": other_token},
    )

    assert response.status_code == 403


def test_an_edit_that_breaks_a_domain_rule_answers_400(client):
    reservation, owner_token = _create(client)

    response = client.patch(
        f"/reservations/{reservation['id']}",
        json={"match_type": "player_match"},
        headers={"X-Reservation-Token": owner_token},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "플레이어 매치는 계급을 선택하지 않습니다."}


def test_an_edit_with_a_bad_field_answers_422_stating_the_rule(client):
    reservation, owner_token = _create(client)

    response = client.patch(
        f"/reservations/{reservation['id']}",
        json={"duration_minutes": 45},
        headers={"X-Reservation-Token": owner_token},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "예상 시간은 30분, 60분, 120분, 180분 중에서 선택해 주세요."}


def test_a_reservation_someone_joined_can_no_longer_be_edited(client):
    reservation, owner_token = _create(client, match_type="player_match", ranks=[], capacity=2)
    client.post(f"/reservations/{reservation['id']}/participants", json={"display_name": "Joiner", "ranks": []})

    response = client.patch(
        f"/reservations/{reservation['id']}",
        json={"memo": "too late"},
        headers={"X-Reservation-Token": owner_token},
    )

    assert response.status_code == 400
    assert "참가자가 있는 예약" in response.json()["detail"]
