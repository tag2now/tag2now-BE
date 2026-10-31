"""PostgreSQL popup tests. Requires the test compose stack to be running."""

import pytest_asyncio
from sqlalchemy import delete

from popup.domain import parse_image
from popup.entities import PopupRow
from popup.models import PopupContent
from shared.database import close_database, get_session_factory, init_database

PNG = parse_image(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
OTHER = parse_image(b"GIF89a" + b"\0" * 16)
SHOWN = PopupContent("안내", "본문", True, False, True)
HIDDEN = PopupContent("숨김", "", False, True, False)


@pytest_asyncio.fixture
async def repo():
    from popup.adapters.postgresql import PostgresPopupRepository

    await init_database()
    async with get_session_factory()() as session, session.begin():
        await session.execute(delete(PopupRow))
    yield PostgresPopupRepository()
    await close_database()


async def _run(work):
    async with get_session_factory()() as session, session.begin():
        return await work(session)


async def test_create_answers_the_stored_popup(repo):
    popup = await _run(lambda s: repo.create(s, SHOWN, PNG, "admin"))

    assert popup.content == SHOWN
    assert (popup.image_hash, popup.created_by) == (PNG.hash, "admin")
    assert popup.created_at == popup.updated_at


async def test_a_list_is_newest_first_and_can_leave_out_the_inactive(repo):
    first = await _run(lambda s: repo.create(s, SHOWN, PNG, "admin"))
    hidden = await _run(lambda s: repo.create(s, HIDDEN, None, "admin"))
    last = await _run(lambda s: repo.create(s, SHOWN, None, "admin"))

    everything = await _run(lambda s: repo.list_popups(s, active_only=False))
    active = await _run(lambda s: repo.list_popups(s, active_only=True))

    assert [p.id for p in everything] == [last.id, hidden.id, first.id]
    assert [p.id for p in active] == [last.id, first.id]


async def test_an_image_comes_back_byte_for_byte(repo):
    popup = await _run(lambda s: repo.create(s, SHOWN, PNG, "admin"))

    assert await _run(lambda s: repo.get_image(s, popup.id)) == PNG


async def test_a_popup_without_an_image_has_none(repo):
    popup = await _run(lambda s: repo.create(s, SHOWN, None, "admin"))

    assert await _run(lambda s: repo.get_image(s, popup.id)) is None
    assert await _run(lambda s: repo.get_image(s, popup.id + 1)) is None


async def test_an_update_keeps_the_image_unless_told_otherwise(repo):
    popup = await _run(lambda s: repo.create(s, SHOWN, PNG, "admin"))

    updated = await _run(lambda s: repo.update(s, popup.id, HIDDEN, None, False))

    assert updated.content == HIDDEN
    assert updated.image_hash == PNG.hash
    assert updated.updated_at > popup.updated_at
    assert await _run(lambda s: repo.get_image(s, popup.id)) == PNG


async def test_an_update_replaces_the_image(repo):
    popup = await _run(lambda s: repo.create(s, SHOWN, PNG, "admin"))

    updated = await _run(lambda s: repo.update(s, popup.id, SHOWN, OTHER, False))

    assert updated.image_hash == OTHER.hash
    assert await _run(lambda s: repo.get_image(s, popup.id)) == OTHER


async def test_an_update_removes_the_image(repo):
    popup = await _run(lambda s: repo.create(s, SHOWN, PNG, "admin"))

    updated = await _run(lambda s: repo.update(s, popup.id, SHOWN, None, True))

    assert updated.image_hash is None
    assert await _run(lambda s: repo.get_image(s, popup.id)) is None


async def test_updating_a_missing_popup_answers_none(repo):
    assert await _run(lambda s: repo.update(s, 1, SHOWN, None, False)) is None


async def test_delete_says_whether_it_found_one(repo):
    popup = await _run(lambda s: repo.create(s, SHOWN, PNG, "admin"))

    assert await _run(lambda s: repo.delete(s, popup.id)) is True
    assert await _run(lambda s: repo.delete(s, popup.id)) is False
    assert await _run(lambda s: repo.list_popups(s, active_only=False)) == []
