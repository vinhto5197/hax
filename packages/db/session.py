import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


def to_async_url(url: str) -> str:
    # SQLAlchemy needs an explicit driver scheme for async; rewrite here so
    # .env stays driver-agnostic. The ONLY place this rewrite may live.
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


_RAW_URL = os.getenv("DATABASE_URL", "postgresql://hax_app:hax_app@localhost:5432/hax")
DATABASE_URL_ASYNC = to_async_url(_RAW_URL)

# Owner-role URL for Alembic/admin tooling (DDL needs ownership; the runtime
# role deliberately can't). Falls back to DATABASE_URL, which only migrates
# when that URL is itself an owner role — the RLS migration's DDL is refused
# for hax_app.
MIGRATIONS_DATABASE_URL_ASYNC = to_async_url(
    os.getenv("MIGRATIONS_DATABASE_URL") or _RAW_URL
)

# hide_parameters=True: DBAPI error strings otherwise append [parameters: …],
# which for the chunk insert is raw user document text — this is the
# load-bearing control against that leaking into worker/CloudWatch logs, not
# any individual log-call tweak.
engine = create_async_engine(DATABASE_URL_ASYNC, hide_parameters=True)
# expire_on_commit=False: the default's post-commit lazy reload isn't awaited in
# async and raises MissingGreenlet. Trade-off: objects keep pre-commit values,
# so refresh() explicitly where DB-computed state is needed.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


from sqlalchemy import event, text  # noqa: E402 — grouped with the listener it serves

from packages.db.user_context import current_user_id  # noqa: E402


@event.listens_for(engine.sync_engine, "begin")
def _announce_rls_identity(conn) -> None:
    # One central place instead of per-callsite SET LOCAL: forgetting at a
    # callsite is exactly the leak class this listener removes. set_config(...,
    # true) == SET LOCAL — dies at transaction end, so pooled connections are
    # handed back identity-free (pool-bleed fence).
    uid = current_user_id.get()
    if uid is not None:
        conn.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"),
            {"uid": str(uid)},
        )


async def assert_rls_bound_role() -> None:
    """Refuse to serve as a role that bypasses RLS (superuser / BYPASSRLS): the
    second isolation layer would be silently decorative. Refuse to serve as
    the schema owner too: RDS's master user is neither superuser nor
    BYPASSRLS (FORCE keeps it RLS-bound) but owns every table, so ownership
    is a separate, equally disqualifying condition. Called at API startup and
    worker-process init."""
    async with engine.connect() as conn:
        bypasses_rls, owns_tables = (
            await conn.execute(
                text(
                    "SELECT"
                    " (SELECT rolsuper OR rolbypassrls FROM pg_roles"
                    "  WHERE rolname = current_user) AS bypasses_rls,"
                    " EXISTS (SELECT 1 FROM pg_tables"
                    "  WHERE schemaname = 'public' AND tableowner = current_user)"
                    "  AS owns_tables"
                )
            )
        ).one()
    reasons = []
    if bypasses_rls:
        reasons.append("connects as an RLS-bypassing role")
    if owns_tables:
        reasons.append("connects as the schema owner")
    if reasons:
        raise RuntimeError(
            f"DATABASE_URL {' and '.join(reasons)}; use the app role (hax_app)"
        )
