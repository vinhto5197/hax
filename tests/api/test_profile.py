"""A member's note about themselves: GET /api/me/profile returns it (null when
there is none); PUT stores the stripped text and returns what is stored; an
empty or blank PUT deletes it; more than 1000 characters after the strip, or
a NUL character, is a 422 that leaves the stored note alone. A visitor gets
the demo refusal on both. Deleting the user deletes the note. The note's text
never reaches the log.

Seeds and asserts go through admin_engine; requests go through the app."""

import logging

import pytest
from sqlalchemy import text

from tests.api.conftest import bearer
from tests.api.factories import make_visitor

URL = "/api/me/profile"
NOTE = "I am a backend engineer; give me terse answers with code."


async def _stored(admin_engine, user_id) -> list[str]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT about FROM user_profiles WHERE user_id = :u"), {"u": user_id}
        )
        return [about for (about,) in rows]


async def _put(client, user, about):
    return await client.put(URL, json={"about": about}, headers=bearer(user))


async def test_get_with_no_note_returns_null(client, user_a):
    r = await client.get(URL, headers=bearer(user_a))
    assert r.status_code == 200
    assert r.json() == {"about": None}


async def test_put_stores_the_note_and_returns_it(client, admin_engine, user_a):
    r = await _put(client, user_a, NOTE)
    assert r.status_code == 200
    assert r.json() == {"about": NOTE}
    assert await _stored(admin_engine, user_a.id) == [NOTE]


async def test_get_after_put_returns_the_saved_note(client, user_a):
    await _put(client, user_a, NOTE)
    r = await client.get(URL, headers=bearer(user_a))
    assert r.status_code == 200
    assert r.json() == {"about": NOTE}


async def test_put_strips_surrounding_whitespace_before_storing(
    client, admin_engine, user_a
):
    r = await _put(client, user_a, f"  \n\t{NOTE} \n ")
    assert r.status_code == 200
    assert r.json() == {"about": NOTE}
    assert await _stored(admin_engine, user_a.id) == [NOTE]


async def test_a_second_put_replaces_the_note(client, admin_engine, user_a):
    await _put(client, user_a, "first version")
    r = await _put(client, user_a, NOTE)
    assert r.json() == {"about": NOTE}
    assert await _stored(admin_engine, user_a.id) == [NOTE]


@pytest.mark.parametrize("empty", ["", "   \n\t  "], ids=["empty", "blank"])
async def test_an_empty_put_deletes_the_note(client, admin_engine, user_a, empty):
    await _put(client, user_a, NOTE)
    r = await _put(client, user_a, empty)
    assert r.status_code == 200
    assert r.json() == {"about": None}
    assert await _stored(admin_engine, user_a.id) == []
    after = await client.get(URL, headers=bearer(user_a))
    assert after.json() == {"about": None}


async def test_an_empty_put_with_no_note_returns_null(client, admin_engine, user_a):
    r = await _put(client, user_a, "")
    assert r.status_code == 200
    assert r.json() == {"about": None}
    assert await _stored(admin_engine, user_a.id) == []


async def test_exactly_1000_characters_is_stored(client, admin_engine, user_a):
    about = "x" * 1000
    r = await _put(client, user_a, about)
    assert r.status_code == 200
    assert await _stored(admin_engine, user_a.id) == [about]


async def test_1000_characters_plus_surrounding_whitespace_is_stored_stripped(
    client, admin_engine, user_a
):
    about = "x" * 1000
    r = await _put(client, user_a, f"  {about}  ")
    assert r.status_code == 200
    assert r.json() == {"about": about}


async def test_1000_emoji_count_as_1000_characters_and_are_stored(
    client, admin_engine, user_a
):
    # Characters are code points, as Postgres char_length counts them; an
    # emoji outside the BMP is two UTF-16 units but one character.
    about = "\U0001f600" * 1000
    r = await _put(client, user_a, about)
    assert r.status_code == 200
    assert await _stored(admin_engine, user_a.id) == [about]


async def test_1001_characters_is_refused_with_422_and_the_note_is_unchanged(
    client, admin_engine, user_a
):
    await _put(client, user_a, NOTE)
    r = await _put(client, user_a, "x" * 1001)
    assert r.status_code == 422
    assert await _stored(admin_engine, user_a.id) == [NOTE]


async def test_a_nul_character_is_refused_with_422_and_nothing_is_stored(
    client, admin_engine, user_a
):
    r = await _put(client, user_a, "before\x00after")
    assert r.status_code == 422
    assert await _stored(admin_engine, user_a.id) == []


async def test_a_body_without_about_is_refused_with_422(client, user_a):
    r = await client.put(URL, json={}, headers=bearer(user_a))
    assert r.status_code == 422


async def test_unauthenticated_get_and_put_are_refused(client):
    assert (await client.get(URL)).status_code == 401
    assert (await client.put(URL, json={"about": NOTE})).status_code == 401


async def test_a_visitor_gets_the_demo_refusal_on_get(client, admin_engine):
    visitor = await make_visitor(admin_engine)
    r = await client.get(URL, headers=bearer(visitor, anonymous=True))
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}


async def test_a_visitor_gets_the_demo_refusal_on_put_and_nothing_is_stored(
    client, admin_engine
):
    visitor = await make_visitor(admin_engine)
    r = await client.put(
        URL, json={"about": NOTE}, headers=bearer(visitor, anonymous=True)
    )
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}
    assert await _stored(admin_engine, visitor.id) == []


@pytest.mark.parametrize("about", ["x" * 1001, "a\x00b"])
async def test_a_visitor_gets_the_demo_refusal_on_put_even_with_an_invalid_body(
    client, admin_engine, about
):
    visitor = await make_visitor(admin_engine)
    r = await client.put(
        URL, json={"about": about}, headers=bearer(visitor, anonymous=True)
    )
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}


async def test_deleting_the_user_deletes_their_note(client, admin_engine, user_a):
    await _put(client, user_a, NOTE)
    async with admin_engine.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_a.id})
    async with admin_engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM user_profiles"))
    assert count == 0


async def test_the_notes_text_never_appears_in_the_log_on_save_read_or_refusal(
    client, user_a, caplog
):
    caplog.set_level(logging.DEBUG)
    await _put(client, user_a, NOTE)
    await client.get(URL, headers=bearer(user_a))
    await _put(client, user_a, NOTE + " " + "y" * 1000)
    await _put(client, user_a, NOTE + "\x00")
    await _put(client, user_a, "")
    assert "backend engineer" not in caplog.text
