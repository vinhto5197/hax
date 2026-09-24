"""The migration environment must hand the database URL straight to SQLAlchemy,
never through Alembic's ConfigParser-backed config: a bare "%" there is
interpolation syntax, and a percent-encoded password contains one."""

import os
import subprocess
import sys
from pathlib import Path


def test_env_never_stores_the_url_in_the_ini_config():
    source = Path("packages/db/migrations/env.py").read_text()
    assert "set_main_option" not in source
    assert 'get_main_option("sqlalchemy.url")' not in source
    assert "async_engine_from_config" not in source


def test_migrations_run_with_a_percent_encoded_password():
    # "h%61x" decodes to the test role's password: the same credentials, spelled
    # the way any password with a reserved character must be.
    url = "postgresql://hax:h%61x@localhost:5432/hax_test"
    env = {**os.environ, "DATABASE_URL": url, "MIGRATIONS_DATABASE_URL": url}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "current"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "(head)" in proc.stdout
