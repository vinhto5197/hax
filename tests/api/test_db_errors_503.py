"""A request stopped by the database's own limits (lock_not_available, the
app's lock_timeout; query_canceled, its statement_timeout) answers 503 with a
fixed, retryable message; every other database error stays a 500. Neither
answer carries SQL, parameters or the driver's message.

The lock case is staged with a real row lock held from the owner connection;
the other errors are real driver errors raised once on the owner connection
and replayed from a route's repo call, so the handler sees exactly what the
driver produces."""

import asyncio
import logging

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from packages.db.repos import conversations as conversations_repo
from tests.api.conftest import bearer
from tests.api.factories import make_conversation

BUSY = "The server is busy right now. Try again in a moment."

SQL_MARKER = "hax_sql_marker_7f3a"
PARAM_MARKER = "hax_param_marker_91c2"


@pytest.fixture
async def raw_client():
    """A client that turns an unhandled app exception into the 500 a browser
    would see, instead of re-raising it into the test."""
    from apps.api.main import app

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _capture(admin_engine, sql: str, params: dict, setup: tuple = ()):
    async with admin_engine.connect() as conn:
        for stmt in setup:
            await conn.execute(text(stmt))
        try:
            await conn.execute(text(sql), params)
        except DBAPIError as exc:
            return exc
    raise AssertionError("the staged statement did not fail")


async def _query_canceled(admin_engine) -> DBAPIError:
    exc = await _capture(
        admin_engine,
        f"SELECT pg_sleep(2), CAST(:p AS text) AS {SQL_MARKER}",
        {"p": PARAM_MARKER},
        setup=("SET LOCAL statement_timeout = '50ms'",),
    )
    assert getattr(exc.orig, "sqlstate", None) == "57014", exc
    return exc


async def _lock_not_available(admin_engine, user_id) -> DBAPIError:
    async with admin_engine.connect() as holder:
        await holder.execute(
            text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": user_id}
        )
        exc = await _capture(
            admin_engine,
            f"SELECT id AS {SQL_MARKER}, CAST(:p AS text) FROM users"
            " WHERE id = :id FOR UPDATE",
            {"p": PARAM_MARKER, "id": user_id},
            setup=("SET LOCAL lock_timeout = '50ms'",),
        )
        await holder.rollback()
    assert getattr(exc.orig, "sqlstate", None) == "55P03", exc
    return exc


async def _unique_violation(admin_engine, email: str) -> DBAPIError:
    exc = await _capture(
        admin_engine,
        f"INSERT INTO users (email, sessions_valid_after)"
        f" SELECT :e, now() WHERE CAST(:p AS text) <> '{SQL_MARKER}'",
        {"e": email, "p": PARAM_MARKER},
    )
    assert isinstance(exc, IntegrityError), exc
    return exc


async def _division_by_zero(admin_engine) -> DBAPIError:
    return await _capture(
        admin_engine,
        f"SELECT 1 / 0 AS {SQL_MARKER}, CAST(:p AS text)",
        {"p": PARAM_MARKER},
    )


def _make_delete_raise(monkeypatch, exc: BaseException) -> None:
    async def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(conversations_repo, "delete_owned", boom)


def _assert_busy(r: httpx.Response) -> None:
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": BUSY}
    assert r.headers.get("retry-after") == "5"


def _assert_no_leak(r: httpx.Response, exc: DBAPIError) -> None:
    body = r.text
    assert SQL_MARKER not in body
    assert PARAM_MARKER not in body
    assert str(exc.orig) not in body
    for word in ("SELECT", "INSERT", "users", "asyncpg", "sqlstate", "timeout"):
        assert word.lower() not in body.lower(), word


async def test_a_request_blocked_by_another_sessions_row_lock_answers_503_busy(
    raw_client, admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    async with admin_engine.connect() as holder:
        await holder.execute(
            text("SELECT id FROM conversations WHERE id = :id FOR UPDATE"),
            {"id": conv},
        )
        # The app's lock_timeout ends the wait; the cap only stops a
        # regression from hanging the suite.
        r = await asyncio.wait_for(
            raw_client.delete(f"/api/conversations/{conv}", headers=bearer(user_a)),
            20,
        )
        await holder.rollback()

    _assert_busy(r)


async def test_a_request_stopped_by_the_statement_timeout_answers_503_busy(
    raw_client, admin_engine, user_a, monkeypatch
):
    conv = await make_conversation(admin_engine, user_a.id)
    _make_delete_raise(monkeypatch, await _query_canceled(admin_engine))

    r = await raw_client.delete(f"/api/conversations/{conv}", headers=bearer(user_a))

    _assert_busy(r)


async def test_a_lock_timeout_raised_from_a_route_answers_503_busy(
    raw_client, admin_engine, user_a, monkeypatch
):
    conv = await make_conversation(admin_engine, user_a.id)
    _make_delete_raise(monkeypatch, await _lock_not_available(admin_engine, user_a.id))

    r = await raw_client.delete(f"/api/conversations/{conv}", headers=bearer(user_a))

    _assert_busy(r)


async def test_an_unhandled_unique_violation_is_still_a_500_not_503(
    raw_client, admin_engine, user_a, monkeypatch
):
    conv = await make_conversation(admin_engine, user_a.id)
    _make_delete_raise(monkeypatch, await _unique_violation(admin_engine, user_a.email))

    r = await raw_client.delete(f"/api/conversations/{conv}", headers=bearer(user_a))

    assert r.status_code == 500
    assert "retry-after" not in r.headers
    assert BUSY not in r.text


async def test_any_other_database_error_is_still_a_500_not_503(
    raw_client, admin_engine, user_a, monkeypatch
):
    conv = await make_conversation(admin_engine, user_a.id)
    _make_delete_raise(monkeypatch, await _division_by_zero(admin_engine))

    r = await raw_client.delete(f"/api/conversations/{conv}", headers=bearer(user_a))

    assert r.status_code == 500
    assert "retry-after" not in r.headers
    assert BUSY not in r.text


@pytest.mark.parametrize("kind", ["query_canceled", "lock_not_available"])
async def test_the_busy_answer_never_carries_sql_parameters_or_the_driver_message(
    raw_client, admin_engine, user_a, monkeypatch, kind
):
    conv = await make_conversation(admin_engine, user_a.id)
    if kind == "query_canceled":
        exc = await _query_canceled(admin_engine)
    else:
        exc = await _lock_not_available(admin_engine, user_a.id)
    # The staged error does carry all three, so their absence below is the
    # handler's doing.
    assert SQL_MARKER in str(exc) and PARAM_MARKER in str(exc)
    _make_delete_raise(monkeypatch, exc)

    r = await raw_client.delete(f"/api/conversations/{conv}", headers=bearer(user_a))

    _assert_busy(r)
    _assert_no_leak(r, exc)


@pytest.mark.parametrize(
    ("kind", "sqlstate"),
    [("query_canceled", "57014"), ("lock_not_available", "55P03")],
)
async def test_the_busy_answer_logs_one_warning_with_route_pattern_and_sqlstate_only(
    raw_client, admin_engine, user_a, monkeypatch, caplog, kind, sqlstate
):
    conv = await make_conversation(admin_engine, user_a.id)
    if kind == "query_canceled":
        exc = await _query_canceled(admin_engine)
    else:
        exc = await _lock_not_available(admin_engine, user_a.id)
    _make_delete_raise(monkeypatch, exc)
    caplog.set_level(logging.WARNING)

    r = await raw_client.delete(f"/api/conversations/{conv}", headers=bearer(user_a))

    _assert_busy(r)
    named = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "DELETE /api/conversations/{conversation_id}" in rec.getMessage()
    ]
    assert len(named) == 1, [rec.getMessage() for rec in caplog.records]
    message = named[0].getMessage()
    assert sqlstate in message
    # Nothing from the statement, its parameters, the request's ids or the
    # driver reaches any log line of this request.
    for rec in caplog.records:
        logged = rec.getMessage()
        assert SQL_MARKER not in logged
        assert PARAM_MARKER not in logged
        assert str(conv) not in logged
        assert str(user_a.id) not in logged
        assert str(exc.orig) not in logged
