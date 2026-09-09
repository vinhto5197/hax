"""Fail-closed role probe (AR-2026-09-08 #2): the app must refuse to serve as
a role that bypasses RLS. Exercised directly against packages.db.session so
the assertion covers the exact function wired into the API lifespan and the
worker's worker_process_init, independent of whether either harness actually
runs it under this test's transport (see test module docstring below)."""

import pytest
from celery.signals import worker_process_init

import apps.worker.celery_app  # noqa: F401 — import connects the real receiver
import packages.db.session as session_module


async def test_app_role_passes():
    # packages.db.session.engine connects as hax_app (see tests/conftest.py) —
    # NOSUPERUSER NOBYPASSRLS per infra/docker-compose/postgres/init.sql.
    await session_module.assert_rls_bound_role()


async def test_superuser_role_raises(admin_engine, monkeypatch):
    # admin_engine connects as hax (superuser in dev/CI) — the exact shape
    # the probe exists to catch. hax also owns hax_test's tables, so both
    # conditions are true here; the RLS-bypass wording is enough to cover
    # this case (test_admin_role_message_names_owner_condition below is what
    # proves the ownership condition is independently detected).
    monkeypatch.setattr(session_module, "engine", admin_engine)
    with pytest.raises(RuntimeError, match="RLS-bypassing role"):
        await session_module.assert_rls_bound_role()


async def test_admin_role_message_names_owner_condition(admin_engine, monkeypatch):
    # hax is the migration owner (Alembic runs DDL as it) so it owns every
    # table in hax_test's public schema — the RDS-master shape this check
    # exists for (neither superuser nor BYPASSRLS there, but still owner).
    # hax is ALSO superuser in dev/CI, so both conditions fire; the message
    # must name the ownership condition regardless, not just the stronger one.
    monkeypatch.setattr(session_module, "engine", admin_engine)
    with pytest.raises(RuntimeError, match="schema owner"):
        await session_module.assert_rls_bound_role()


def test_worker_process_init_signal_passes_with_app_role():
    # Drives the REAL celery signal, not just the underlying function: proves
    # apps.worker.celery_app's receiver is actually connected and, on a
    # bound-role engine, worker_process_init.send() returns normally.
    worker_process_init.send(sender=None)


def test_worker_process_init_signal_aborts_worker_with_superuser_role(
    admin_engine, monkeypatch
):
    # Celery's Signal.send wraps each receiver in try/except Exception (logs,
    # continues) — a plain RuntimeError from the probe would be swallowed and
    # the prefork child would start pulling tasks as the bypassing role
    # anyway. The handler re-raises SystemExit, a BaseException, which is NOT
    # caught by that guard and propagates out of send() itself — that's what
    # this test proves end-to-end through the real signal, not just the
    # handler function in isolation.
    monkeypatch.setattr(session_module, "engine", admin_engine)
    with pytest.raises(SystemExit):
        worker_process_init.send(sender=None)
