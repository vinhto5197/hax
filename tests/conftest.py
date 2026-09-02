import os

# Deterministic env for tests. Set BEFORE app modules import (conftest runs
# first); hard-assign, don't setdefault — tests must never see real .env
# values. DATABASE_URL points at hax_test so the suite structurally cannot
# touch dev data; the app role/admin split mirrors dev (Task 0).
# >=32 bytes: PyJWT's HMAC-SHA256 key-length check warns below the digest
# size, and CI runs pytest -W error, so a shorter fake secret fails the suite.
os.environ["AUTH_SECRET"] = "test-secret-not-for-real-use-pad"
os.environ["INTERNAL_API_SECRET"] = "test-internal-secret"
os.environ["DATABASE_URL"] = "postgresql://hax_app:hax_app@localhost:5432/hax_test"
os.environ["MIGRATIONS_DATABASE_URL"] = "postgresql://hax:hax@localhost:5432/hax_test"
# Never used (fakeredis is patched in); unroutable port so a miss fails fast.
os.environ["REDIS_URL"] = "redis://localhost:1/0"
# SDK clients are constructed at import; keys must exist but are never used —
# no test may reach the network.
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
os.environ["VOYAGE_API_KEY"] = "test-not-a-real-key"
