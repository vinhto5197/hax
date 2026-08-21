"""Dev utility: set or replace a user's password directly.

Exists to claim the bootstrap user before slice 4's proper reset flow ships
(and as a local admin escape hatch after). Never wired into the app.

Usage: .venv/bin/python scripts/set_password.py you@example.com
"""

import asyncio
import getpass
import sys

from dotenv import load_dotenv

# BEFORE the packages imports: packages/db/session.py freezes DATABASE_URL at
# import time, so the .env must be in os.environ first or a shell without
# direnv silently falls back to the localhost default (wrong-DB trap).
load_dotenv()

from sqlalchemy import func, select  # noqa: E402

from packages.core.auth.passwords import hash_password  # noqa: E402
from packages.db import AsyncSessionLocal  # noqa: E402
from packages.db.models import User  # noqa: E402


async def main(email: str) -> int:
    password = getpass.getpass("New password (8-128 chars): ")
    if not 8 <= len(password) <= 128:
        print("password must be 8-128 characters")
        return 1
    async with AsyncSessionLocal() as session:
        result = await session.scalars(
            select(User).where(func.lower(User.email) == email.strip().lower())
        )
        user = result.first()
        if user is None:
            print(f"no user with email {email}")
            return 1
        user.password_hash = hash_password(password)
        await session.commit()
    print(f"password set for {email}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
