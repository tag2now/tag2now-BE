"""Reservation HTTP contract: what a client actually receives, good request or bad.

Requires the test compose stack to be running.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from reservation.entities import Reservation as ReservationRow
from reservation.entities import ReservationComment as ReservationCommentRow
from reservation.entities import ReservationParticipant as ReservationParticipantRow

KST = ZoneInfo("Asia/Seoul")


def _empty_reservation_tables():
    """Delete the reservation rows through the app's own session factory.

    TRUNCATE would do the same in one statement, but it takes an ACCESS
    EXCLUSIVE lock and CASCADEs into whatever else comes to reference these
    tables later. A plain DELETE names exactly the three tables the suite owns
    and behaves like any other write, which matters because a local dev server
    is usually pointed at this same database.
    """
    from shared.database import close_database, get_session_factory, init_database

    async def _run():
        await init_database()
        try:
            async with get_session_factory()() as session, session.begin():
                await session.execute(delete(ReservationCommentRow))
                await session.execute(delete(ReservationParticipantRow))
                await session.execute(delete(ReservationRow))
        finally:
            await close_database()

    asyncio.run(_run())


@pytest.fixture()
def client():
    """A client over an empty reservations table, left empty for the next test.

    The assertions here look for their own row by id rather than counting, so
    they survive a stray row; the emptying is what stops a suite that creates a
    reservation per test from growing the table without bound, and what keeps a
    listing test honest if someone later writes one that does count.
    """
    from app import app

    _empty_reservation_tables()
    with TestClient(app) as tc:
        yield tc
    _empty_reservation_tables()


@pytest.fixture()
def as_user(auth_headers):
    """as_user("host") -> headers signed in as that RPCN account.

    The online name is the username capitalised, so a test can tell which of
    the two a response carries.
    """
    return lambda username: auth_headers(username, online_name=username.capitalize())


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
        "ranks": ["Brawler"],
        "match_type": "rank_match",
        "capacity": 1,
        "memo": "",
    }
    return {**body, **overrides}


def test_a_schema_violation_states_the_rule_that_failed(client, as_user):
    response = client.post("/reservations", json=_payload(ranks=["Brawler", "Brawler"]), headers=as_user("host"))

    assert response.status_code == 422
    assert response.json() == {"detail": "같은 계급을 중복해서 선택할 수 없습니다."}


def test_one_rule_is_answered_even_when_several_fields_fail(client, as_user):
    """A form shows one line, so the first violation that names a rule wins.

    Both of these are specific, and pydantic reports them in field order --- the
    point is that neither falls back to naming its field, which used to let the
    vaguer of the two mask the other.
    """
    response = client.post("/reservations", json=_payload(ranks=["Brawler", "Brawler"], memo="A" * 141), headers=as_user("host"))

    assert response.status_code == 422
    assert response.json()["detail"] == "같은 계급을 중복해서 선택할 수 없습니다."


def test_a_domain_rule_answers_400_with_its_own_message(client, as_user):
    response = client.post("/reservations", json=_payload(ranks=[]), headers=as_user("host"))

    assert response.status_code == 400
    assert response.json() == {"detail": "랭크매치는 보유 계급을 하나 이상 선택해야 합니다."}


def test_both_failure_kinds_share_one_response_shape(client, as_user):
    """Statuses differ by kind, but a client parses one body shape either way."""
    schema = client.post("/reservations", json=_payload(ranks=["Brawler", "Brawler"]), headers=as_user("host"))
    domain = client.post("/reservations", json=_payload(ranks=[]), headers=as_user("host"))

    assert (schema.status_code, domain.status_code) == (422, 400)
    assert list(schema.json()) == list(domain.json()) == ["detail"]
    assert all(isinstance(r.json()["detail"], str) for r in (schema, domain))


# --- Signing in --------------------------------------------------------------


@pytest.mark.parametrize("method, path, body", [
    ("post", "/reservations", {"start_time": "20:00", "match_type": "any"}),
    ("patch", "/reservations/1", {"memo": "x"}),
    ("delete", "/reservations/1", None),
    ("post", "/reservations/1/participants", {"ranks": []}),
    ("delete", "/reservations/1/participants/me", None),
    ("post", "/reservations/1/comments", {"body": "x"}),
    ("delete", "/reservations/1/comments/1", None),
])
def test_every_write_needs_a_signed_in_user(client, method, path, body):
    response = client.request(method.upper(), path, json=body)

    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요합니다."}


def test_reads_need_no_sign_in(client, as_user):
    reservation = _create(client, as_user("host"))

    assert client.get("/reservations").status_code == 200
    assert client.get(f"/reservations/{reservation['id']}").status_code == 200
    assert client.get(f"/reservations/{reservation['id']}/comments").status_code == 200


# --- Success paths -----------------------------------------------------------
# The cases above cover how a bad request comes back. The rest of this file
# covers the other half of the contract: what a client receives when the request
# is good, and whether the domain rules survive the trip through HTTP.


def _create(client, headers, **overrides):
    response = client.post("/reservations", json=_payload(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _join(client, reservation_id, headers, ranks=()):
    return client.post(f"/reservations/{reservation_id}/participants", json={"ranks": list(ranks)}, headers=headers)


def test_creating_a_reservation_answers_the_row_with_the_signed_in_host(client, as_user):
    reservation = _create(client, as_user("host"))

    assert reservation["status"] == "open"
    assert reservation["participant_count"] == 0
    assert reservation["host_display_name"] == "Host"
    assert reservation["host_username"] == "host"
    assert reservation["match_type"] == "rank_match"


def test_the_host_name_comes_from_the_account_not_the_body(client, as_user):
    """A body that tries to name someone else is simply not read."""
    reservation = _create(client, as_user("host"), display_name="Somebody Else")

    assert reservation["host_display_name"] == "Host"


def test_a_match_type_of_any_keeps_both_its_ranks_and_a_larger_capacity(client, as_user):
    reservation = _create(client, as_user("host"), match_type="any", ranks=["Brawler"], capacity=2)

    assert reservation["match_type"] == "any"
    assert reservation["host_ranks"] == ["Brawler"]
    assert reservation["capacity"] == 2


def test_a_new_reservation_is_listed_without_asking_for_a_date(client, as_user):
    reservation = _create(client, as_user("host"))

    listed = client.get("/reservations")

    assert listed.status_code == 200
    assert reservation["id"] in [item["id"] for item in listed.json()]


def test_a_time_of_day_past_dawn_is_refused(client, as_user):
    """The window ends at 06:00 KST, so nothing can be booked into the day after."""
    response = client.post("/reservations", json=_payload(start_time=_unbookable_time_of_day()), headers=as_user("host"))

    assert response.status_code == 400
    assert "오전 6시" in response.json()["detail"]


def test_fetching_one_reservation_returns_the_same_row_the_creation_did(client, as_user):
    reservation = _create(client, as_user("host"))

    fetched = client.get(f"/reservations/{reservation['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == reservation


def test_fetching_a_reservation_that_never_existed_is_a_404(client):
    response = client.get("/reservations/99999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Reservation not found"}


def test_joining_fills_a_rank_match(client, as_user):
    reservation = _create(client, as_user("host"))

    response = _join(client, reservation["id"], as_user("joiner"))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "matched"
    assert body["participant_count"] == 1
    assert body["participants"][0]["username"] == "joiner"
    assert body["participants"][0]["display_name"] == "Joiner"


def test_joining_a_reservation_that_never_existed_is_a_404(client, as_user):
    response = _join(client, 99999999, as_user("joiner"))

    assert response.status_code == 404


def test_the_host_cannot_join_their_own_reservation(client, as_user):
    reservation = _create(client, as_user("host"), match_type="player_match", ranks=[], capacity=2)

    response = _join(client, reservation["id"], as_user("host"))

    assert response.status_code == 400
    assert response.json() == {"detail": "내가 만든 예약에는 참가할 수 없습니다."}


def test_one_account_holds_one_seat(client, as_user):
    reservation = _create(client, as_user("host"), match_type="player_match", ranks=[], capacity=3)
    _join(client, reservation["id"], as_user("joiner"))

    response = _join(client, reservation["id"], as_user("joiner"))

    assert response.status_code == 400
    assert response.json() == {"detail": "이미 참가한 예약입니다."}


def test_a_participant_who_cancelled_can_join_again(client, as_user):
    reservation = _create(client, as_user("host"))
    _join(client, reservation["id"], as_user("joiner"))
    client.delete(f"/reservations/{reservation['id']}/participants/me", headers=as_user("joiner"))

    response = _join(client, reservation["id"], as_user("joiner"))

    assert response.status_code == 201


def test_roster_is_ordered_public_and_excludes_cancelled_participants(client, as_user):
    reservation = _create(client, as_user("host"), match_type="player_match", ranks=[], capacity=2)
    reservation_id = reservation["id"]
    assert reservation["participants"] == []
    _join(client, reservation_id, as_user("first"))
    second = _join(client, reservation_id, as_user("second")).json()
    roster = second["participants"]
    assert [p["display_name"] for p in roster] == ["First", "Second"]
    assert all(set(p) == {"id", "display_name", "username"} for p in roster)
    assert second["status"] == "matched"
    assert client.get(f"/reservations/{reservation_id}").json()["participants"] == roster
    listed = next(r for r in client.get("/reservations").json() if r["id"] == reservation_id)
    assert listed["participants"] == roster
    cancelled = client.delete(f"/reservations/{reservation_id}/participants/me", headers=as_user("first"))
    assert cancelled.status_code == 200
    assert cancelled.json()["participants"] == [roster[1]]
    assert cancelled.json()["participant_count"] == 1
    assert cancelled.json()["status"] == "open"
    assert client.get(f"/reservations/{reservation_id}").json()["participants"] == [roster[1]]


def test_joining_past_capacity_is_refused_as_a_domain_violation(client, as_user):
    reservation = _create(client, as_user("host"))
    _join(client, reservation["id"], as_user("first"))

    response = _join(client, reservation["id"], as_user("second"))

    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_a_participant_cancelling_reopens_the_reservation(client, as_user):
    reservation = _create(client, as_user("host"))
    _join(client, reservation["id"], as_user("joiner"))

    response = client.delete(f"/reservations/{reservation['id']}/participants/me", headers=as_user("joiner"))

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    assert response.json()["participant_count"] == 0


def test_someone_who_never_joined_has_no_participation_to_cancel(client, as_user):
    reservation = _create(client, as_user("host"))
    _join(client, reservation["id"], as_user("joiner"))

    response = client.delete(f"/reservations/{reservation['id']}/participants/me", headers=as_user("stranger"))

    assert response.status_code == 403
    assert client.get(f"/reservations/{reservation['id']}").json()["participant_count"] == 1


def test_the_host_cancels_the_reservation_and_it_leaves_the_days_list(client, as_user):
    reservation = _create(client, as_user("host"))

    response = client.delete(f"/reservations/{reservation['id']}", headers=as_user("host"))

    assert response.status_code == 204
    assert client.get(f"/reservations/{reservation['id']}").json()["status"] == "cancelled"
    listed = client.get("/reservations")
    assert reservation["id"] not in [item["id"] for item in listed.json()]


def test_a_participant_cannot_cancel_the_whole_reservation(client, as_user):
    reservation = _create(client, as_user("host"))
    _join(client, reservation["id"], as_user("joiner"))

    response = client.delete(f"/reservations/{reservation['id']}", headers=as_user("joiner"))

    assert response.status_code == 403


def test_editing_a_reservation_answers_the_updated_row(client, as_user):
    reservation = _create(client, as_user("host"))

    response = client.patch(f"/reservations/{reservation['id']}", json={"memo": "자리 하나 남음"}, headers=as_user("host"))

    assert response.status_code == 200
    assert response.json()["memo"] == "자리 하나 남음"


def test_editing_someone_elses_reservation_is_forbidden(client, as_user):
    reservation = _create(client, as_user("host"))

    response = client.patch(f"/reservations/{reservation['id']}", json={"memo": "stolen"}, headers=as_user("other"))

    assert response.status_code == 403
    assert client.get(f"/reservations/{reservation['id']}").json()["memo"] == ""


def test_an_edit_that_breaks_a_domain_rule_answers_400(client, as_user):
    reservation = _create(client, as_user("host"))

    response = client.patch(f"/reservations/{reservation['id']}", json={"match_type": "player_match"}, headers=as_user("host"))

    assert response.status_code == 400
    assert response.json() == {"detail": "플레이어 매치는 계급을 선택하지 않습니다."}


def test_an_edit_with_a_bad_field_answers_422_stating_the_rule(client, as_user):
    reservation = _create(client, as_user("host"))

    response = client.patch(f"/reservations/{reservation['id']}", json={"ranks": ["Brawler", "Brawler"]}, headers=as_user("host"))

    assert response.status_code == 422
    assert response.json() == {"detail": "같은 계급을 중복해서 선택할 수 없습니다."}


def test_a_reservation_someone_joined_can_no_longer_be_edited(client, as_user):
    reservation = _create(client, as_user("host"), match_type="player_match", ranks=[], capacity=2)
    _join(client, reservation["id"], as_user("joiner"))

    response = client.patch(f"/reservations/{reservation['id']}", json={"memo": "too late"}, headers=as_user("host"))

    assert response.status_code == 400
    assert "참가자가 있는 예약" in response.json()["detail"]


def _comment(client, reservation_id, headers, body="21시 괜찮으세요?"):
    response = client.post(f"/reservations/{reservation_id}/comments", json={"body": body}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_comment_is_listed_under_the_reservation_it_was_left_on(client, as_user):
    reservation = _create(client, as_user("host"))

    posted = _comment(client, reservation["id"], as_user("commenter"), body="초보인데 괜찮을까요")

    listed = client.get(f"/reservations/{reservation['id']}/comments").json()
    assert [c["id"] for c in listed] == [posted["id"]]
    assert listed[0]["body"] == "초보인데 괜찮을까요"
    assert listed[0]["author"] == "Commenter"
    assert listed[0]["author_username"] == "commenter"


def test_comments_read_in_the_order_they_were_written(client, as_user):
    reservation = _create(client, as_user("host"))

    for line in ("첫번째", "두번째", "세번째"):
        _comment(client, reservation["id"], as_user("commenter"), body=line)

    listed = client.get(f"/reservations/{reservation['id']}/comments").json()
    assert [c["body"] for c in listed] == ["첫번째", "두번째", "세번째"]


def test_an_author_can_delete_their_own_comment(client, as_user):
    reservation = _create(client, as_user("host"))
    comment = _comment(client, reservation["id"], as_user("commenter"))

    response = client.delete(f"/reservations/{reservation['id']}/comments/{comment['id']}", headers=as_user("commenter"))

    assert response.status_code == 204
    assert client.get(f"/reservations/{reservation['id']}/comments").json() == []


def test_someone_else_cannot_delete_a_comment(client, as_user):
    reservation = _create(client, as_user("host"))
    comment = _comment(client, reservation["id"], as_user("commenter"))

    response = client.delete(f"/reservations/{reservation['id']}/comments/{comment['id']}", headers=as_user("host"))

    assert response.status_code == 403
    assert len(client.get(f"/reservations/{reservation['id']}/comments").json()) == 1


def test_a_deleted_comment_cannot_be_deleted_twice(client, as_user):
    reservation = _create(client, as_user("host"))
    comment = _comment(client, reservation["id"], as_user("commenter"))
    client.delete(f"/reservations/{reservation['id']}/comments/{comment['id']}", headers=as_user("commenter"))

    response = client.delete(f"/reservations/{reservation['id']}/comments/{comment['id']}", headers=as_user("commenter"))

    assert response.status_code == 404


def test_a_comment_on_a_missing_reservation_is_a_404(client, as_user):
    response = client.post("/reservations/9999/comments", json={"body": "있나요"}, headers=as_user("commenter"))

    assert response.status_code == 404


def test_a_cancelled_reservation_stops_taking_comments(client, as_user):
    """A cancelled appointment is not a thing left to discuss."""
    reservation = _create(client, as_user("host"))
    client.delete(f"/reservations/{reservation['id']}", headers=as_user("host"))

    response = client.post(f"/reservations/{reservation['id']}/comments", json={"body": "아쉽네요"}, headers=as_user("commenter"))

    assert response.status_code == 400
    assert response.json() == {"detail": "취소된 예약에는 댓글을 쓸 수 없습니다."}


def test_an_empty_comment_is_refused_before_it_reaches_the_domain(client, as_user):
    reservation = _create(client, as_user("host"))

    response = client.post(f"/reservations/{reservation['id']}/comments", json={"body": "   "}, headers=as_user("commenter"))

    assert response.status_code == 422
