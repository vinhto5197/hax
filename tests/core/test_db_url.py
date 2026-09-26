from packages.db.session import to_async_url


def test_scheme_is_rewritten_once():
    assert to_async_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_libpq_sslmode_becomes_asyncpg_ssl():
    # RDS URLs are written libpq-style; asyncpg rejects an unknown sslmode kwarg.
    assert (
        to_async_url("postgresql://u:p@h/db?sslmode=require")
        == "postgresql+asyncpg://u:p@h/db?ssl=require"
    )


def test_other_query_params_are_kept():
    assert (
        to_async_url("postgresql://u:p@h/db?sslmode=require&application_name=hax")
        == "postgresql+asyncpg://u:p@h/db?ssl=require&application_name=hax"
    )


def test_engine_replaces_dead_pooled_connections():
    from packages.db import engine

    assert engine.pool._pre_ping is True
