"""Isolation of the note about yourself, at three layers: the routes (member B
never reads or overwrites member A's note), the repo's own user_id predicate
(over an admin session RLS cannot answer for), and Postgres RLS alone (the
app role, identity announced as B, asking for A's row). The table is under
FORCE row-level security like every owned table.

Seeds and asserts go through admin_engine (owner); the app engine is hax_app."""

import contextlib

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.db import AsyncSessionLocal
from packages.db.models.user_profile import UserProfile
from packages.db.repos import profiles as profiles_repo
from packages.db.user_context import current_user_id
from tests.api.conftest import bearer

URL = "/api/me/profile"
A_NOTE = "Member A: a cardiologist who wants citations."
B_NOTE = "Member B: a student, explain like I'm new."


async def _seed_note(admin_engine, user_id, about: str) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO user_profiles (user_id, about) VALUES (:u, :a)"),
            {"u": user_id, "a": about},
        )


async def _stored(admin_engine, user_id) -> list[str]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT about FROM user_profiles WHERE user_id = :u"), {"u": user_id}
        )
        return [about for (about,) in rows]


@contextlib.contextmanager
def _identity(user):
    token = current_user_id.set(user.id)
    try:
        yield
    finally:
        current_user_id.reset(token)


# --- Routes -----------------------------------------------------------------


async def test_member_b_reads_null_while_member_a_has_a_note(
    client, admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    r = await client.get(URL, headers=bearer(user_b))
    assert r.status_code == 200
    assert r.json() == {"about": None}


async def test_member_b_saving_a_note_never_overwrites_member_as(
    client, admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    r = await client.put(URL, json={"about": B_NOTE}, headers=bearer(user_b))
    assert r.status_code == 200
    assert await _stored(admin_engine, user_a.id) == [A_NOTE]
    assert await _stored(admin_engine, user_b.id) == [B_NOTE]
    a_reads = await client.get(URL, headers=bearer(user_a))
    assert a_reads.json() == {"about": A_NOTE}


async def test_member_b_clearing_their_note_never_deletes_member_as(
    client, admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    await _seed_note(admin_engine, user_b.id, B_NOTE)
    r = await client.put(URL, json={"about": ""}, headers=bearer(user_b))
    assert r.status_code == 200
    assert await _stored(admin_engine, user_a.id) == [A_NOTE]
    assert await _stored(admin_engine, user_b.id) == []


# --- Repo predicates (admin session: RLS cannot hide a dropped WHERE) -------


async def test_repo_get_about_returns_only_the_named_users_note(
    admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        assert await profiles_repo.get_about(session, user_b.id) is None
        assert await profiles_repo.get_about(session, user_a.id) == A_NOTE


async def test_repo_set_about_writes_only_the_named_users_note(
    admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        assert await profiles_repo.set_about(session, user_b.id, B_NOTE) == B_NOTE
        await session.commit()
    assert await _stored(admin_engine, user_a.id) == [A_NOTE]
    assert await _stored(admin_engine, user_b.id) == [B_NOTE]


async def test_repo_set_about_with_empty_text_deletes_only_the_named_users_note(
    admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    await _seed_note(admin_engine, user_b.id, B_NOTE)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        assert await profiles_repo.set_about(session, user_b.id, "") is None
        await session.commit()
    assert await _stored(admin_engine, user_a.id) == [A_NOTE]
    assert await _stored(admin_engine, user_b.id) == []


# --- RLS alone (app role) ---------------------------------------------------


async def test_user_profiles_is_under_forced_row_level_security(admin_engine):
    async with admin_engine.connect() as conn:
        enabled, forced = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
                    " WHERE relname = 'user_profiles'"
                )
            )
        ).one()
    assert enabled is True
    assert forced is True


async def test_a_connection_without_identity_sees_no_notes(admin_engine, user_a):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(UserProfile))).all()
    assert rows == []


async def test_rls_hides_member_as_note_from_an_unscoped_query_announced_as_b(
    admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    await _seed_note(admin_engine, user_b.id, B_NOTE)
    with _identity(user_b):
        async with AsyncSessionLocal() as session:
            rows = (await session.scalars(select(UserProfile))).all()
    assert [(r.user_id, r.about) for r in rows] == [(user_b.id, B_NOTE)]


async def test_rls_returns_nothing_when_b_asks_the_repo_for_as_note(
    admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    with _identity(user_b):
        async with AsyncSessionLocal() as session:
            assert await profiles_repo.get_about(session, user_a.id) is None


async def test_rls_keeps_b_from_writing_as_note_through_the_repo(
    admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    with _identity(user_b):
        # Refused (WITH CHECK) or a no-op; either way A's note is untouched.
        with contextlib.suppress(DBAPIError):
            async with AsyncSessionLocal() as session:
                await profiles_repo.set_about(session, user_a.id, B_NOTE)
                await session.commit()
    assert await _stored(admin_engine, user_a.id) == [A_NOTE]


async def test_rls_keeps_b_from_deleting_as_note_through_the_repo(
    admin_engine, user_a, user_b
):
    await _seed_note(admin_engine, user_a.id, A_NOTE)
    with _identity(user_b):
        with contextlib.suppress(DBAPIError):
            async with AsyncSessionLocal() as session:
                await profiles_repo.set_about(session, user_a.id, "")
                await session.commit()
    assert await _stored(admin_engine, user_a.id) == [A_NOTE]
