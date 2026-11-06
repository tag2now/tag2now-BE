"""Popup routes over an in-memory repository."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from popup.dependencies import popup_service
from popup.domain import MAX_IMAGE_BYTES
from popup.models import Popup, PopupContent
from popup.ports import PopupRepository
from popup.service import PopupService
from shared.cache import DictCache

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
OTHER_PNG = PNG + b"\1"
FORM = {"title": "이벤트 안내", "body": "첫 줄\n둘째 줄", "active": "true", "allow_dismiss_forever": "true"}


class MemoryRepository(PopupRepository):
    def __init__(self):
        self.rows: dict[int, Popup] = {}
        self.images: dict[int, object] = {}
        self.listed = 0

    async def list_popups(self, session, active_only):
        self.listed += 1
        rows = sorted(self.rows.values(), key=lambda row: row.id, reverse=True)
        return [row for row in rows if row.content.active or not active_only]

    async def get_image(self, session, popup_id):
        return self.images.get(popup_id)

    async def create(self, session, content, image, created_by):
        popup_id = max(self.rows, default=0) + 1
        now = datetime(2026, 10, 31, tzinfo=timezone.utc)
        self.rows[popup_id] = Popup(popup_id, content, image.hash if image else None, created_by, now, now)
        if image:
            self.images[popup_id] = image
        return self.rows[popup_id]

    async def update(self, session, popup_id, content, image, remove_image):
        if popup_id not in self.rows:
            return None
        if remove_image:
            self.images.pop(popup_id, None)
        if image:
            self.images[popup_id] = image
        stored = self.images.get(popup_id)
        self.rows[popup_id] = replace(self.rows[popup_id], content=content, image_hash=stored.hash if stored else None)
        return self.rows[popup_id]

    async def delete(self, session, popup_id):
        self.images.pop(popup_id, None)
        return self.rows.pop(popup_id, None) is not None


@pytest.fixture
def sessions():
    """A session factory whose sessions the in-memory repository ignores."""
    session = AsyncMock()

    @asynccontextmanager
    async def begin():
        yield

    session.begin = begin

    @asynccontextmanager
    async def open_session():
        yield session

    return open_session


@pytest.fixture(autouse=True)
def cache(monkeypatch):
    fresh = DictCache()
    monkeypatch.setattr("popup.service.cache_get", fresh.get)
    monkeypatch.setattr("popup.service.cache_set", fresh.set)
    monkeypatch.setattr("popup.service.cache_delete", fresh.delete)
    return fresh


@pytest.fixture
def repo():
    return MemoryRepository()


@pytest.fixture(autouse=True)
def installed(repo, sessions):
    from app import app

    app.dependency_overrides[popup_service] = lambda: PopupService(repo, sessions)
    yield
    app.dependency_overrides.pop(popup_service, None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import app

    return TestClient(app)  # no `with`: lifespan stays off, the adapters are ours


@pytest.fixture
def admin(auth_headers):
    return auth_headers("admin", admin=True)


def _create(client, admin, image=PNG, content_type="image/png", **fields):
    files = {"image": ("photo.png", image, content_type)} if image is not None else None
    return client.post("/admin/popups", data={**FORM, **fields}, files=files, headers=admin)


# --- visitors -------------------------------------------------------------------


def test_visitors_see_only_active_popups_newest_first(client, admin):
    _create(client, admin, title="첫째")
    _create(client, admin, title="꺼둠", active="false")
    _create(client, admin, image=None, title="셋째")

    popups = client.get("/popups/active").json()["popups"]

    assert [p["title"] for p in popups] == ["셋째", "첫째"]
    assert popups[0]["image_path"] is None
    assert popups[1]["image_path"].startswith("popups/1/image?v=")
    assert "active" not in popups[0] and "created_by" not in popups[0]


def test_a_popup_carries_the_dismiss_buttons_it_was_given(client, admin):
    _create(client, admin, allow_dismiss_forever="false", allow_dismiss_day="true")

    popup = client.get("/popups/active").json()["popups"][0]

    assert (popup["allow_dismiss_forever"], popup["allow_dismiss_day"]) == (False, True)


def test_the_list_is_cached_until_an_admin_writes(client, admin, repo):
    _create(client, admin, title="첫째")
    for _ in range(3):
        client.get("/popups/active")
    assert repo.listed == 1

    _create(client, admin, title="둘째")

    assert len(client.get("/popups/active").json()["popups"]) == 2
    assert repo.listed == 2


def test_an_image_is_served_with_its_own_type_and_cached_for_good(client, admin):
    _create(client, admin)

    answer = client.get("/popups/1/image")

    assert answer.content == PNG
    assert answer.headers["content-type"] == "image/png"
    assert answer.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_a_popup_without_an_image_has_nothing_to_serve(client, admin):
    _create(client, admin, image=None)

    assert client.get("/popups/1/image").status_code == 404
    assert client.get("/popups/99/image").status_code == 404


def test_an_id_past_a_bigint_is_refused_before_the_database(client):
    assert client.get(f"/popups/{2**63}/image").status_code == 422


# --- admin ----------------------------------------------------------------------


def test_create_stores_what_the_admin_set(client, admin, repo):
    answer = _create(client, admin)

    assert answer.status_code == 201
    assert answer.json()["created_by"] == "admin"
    assert repo.rows[1].content == PopupContent("이벤트 안내", "첫 줄\n둘째 줄", True, False, True)


def test_an_image_alone_is_a_popup(client, admin):
    answer = client.post("/admin/popups", data={"title": "이미지만"}, files={"image": ("a.png", PNG)}, headers=admin)

    assert answer.status_code == 201
    assert answer.json()["body"] == ""


def test_a_forms_crlf_line_breaks_are_stored_and_counted_as_one(client, admin, repo):
    body = "가\r\n" * 999 + "가"

    assert _create(client, admin, body=body).status_code == 201

    assert repo.rows[1].content.body == "가\n" * 999 + "가"


def test_the_client_cannot_name_the_stored_type(client, admin, repo):
    _create(client, admin, content_type="image/svg+xml")

    assert repo.images[1].content_type == "image/png"


@pytest.mark.parametrize(
    "image, detail",
    [
        (b"<svg><script>alert(1)</script></svg>", "PNG, JPEG, WebP, GIF 이미지만 올릴 수 있습니다."),
        (PNG.ljust(MAX_IMAGE_BYTES + 1, b"\0"), "이미지는 5MB를 넘을 수 없습니다."),
    ],
    # pytest puts the test id in an environment variable, which Windows caps at 32767 characters.
    ids=["not-an-image", "over-5mb"],
)
def test_a_bad_image_stores_nothing(client, admin, repo, image, detail):
    answer = _create(client, admin, image=image)

    assert (answer.status_code, answer.json()["detail"]) == (400, detail)
    assert repo.rows == {}


@pytest.mark.parametrize(
    "fields, detail",
    [
        ({"title": ""}, "제목을 입력해 주세요."),
        ({"title": "   "}, "제목을 입력해 주세요."),
        ({"title": "가" * 101}, "제목은 100자를 넘을 수 없습니다."),
        ({"body": "가" * 2001}, "내용은 2000자를 넘을 수 없습니다."),
    ],
)
def test_a_bad_form_names_the_field(client, admin, fields, detail):
    answer = _create(client, admin, **fields)

    assert (answer.status_code, answer.json()["detail"]) == (422, detail)


def test_an_edit_without_an_image_keeps_the_stored_one(client, admin):
    before = _create(client, admin).json()["image_path"]

    answer = client.put("/admin/popups/1", data={"title": "고침"}, headers=admin).json()

    assert (answer["title"], answer["image_path"]) == ("고침", before)
    assert client.get("/popups/1/image").content == PNG


def test_a_new_image_replaces_the_old_under_a_new_url(client, admin):
    before = _create(client, admin).json()["image_path"]

    answer = client.put(
        "/admin/popups/1", data={"title": "고침"}, files={"image": ("b.png", OTHER_PNG)}, headers=admin
    ).json()

    assert answer["image_path"] != before
    assert client.get("/popups/1/image").content == OTHER_PNG


def test_remove_image_drops_it(client, admin):
    _create(client, admin)

    answer = client.put("/admin/popups/1", data={"title": "고침", "remove_image": "true"}, headers=admin).json()

    assert answer["image_path"] is None
    assert client.get("/popups/1/image").status_code == 404


def test_an_edit_shows_at_once(client, admin):
    _create(client, admin)
    client.get("/popups/active")

    client.put("/admin/popups/1", data={"title": "고침", "active": "false"}, headers=admin)

    assert client.get("/popups/active").json()["popups"] == []


def test_an_admin_lists_inactive_popups_too(client, admin):
    _create(client, admin, active="false")

    popups = client.get("/admin/popups", headers=admin).json()["popups"]

    assert [(p["title"], p["active"], p["created_by"]) for p in popups] == [("이벤트 안내", False, "admin")]


def test_delete_takes_the_popup_off_the_site(client, admin, repo):
    _create(client, admin)
    client.get("/popups/active")

    assert client.delete("/admin/popups/1", headers=admin).status_code == 204

    assert client.get("/popups/active").json()["popups"] == []
    assert repo.images == {}


def test_a_missing_popup_is_a_404(client, admin):
    assert client.put("/admin/popups/9", data={"title": "없음"}, headers=admin).status_code == 404
    assert client.delete("/admin/popups/9", headers=admin).status_code == 404


@pytest.mark.parametrize(
    "method, path",
    [("get", "/admin/popups"), ("post", "/admin/popups"), ("put", "/admin/popups/1"), ("delete", "/admin/popups/1")],
)
def test_admin_routes_refuse_everyone_else(client, auth_headers, method, path):
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers=auth_headers("alice")).status_code == 403
