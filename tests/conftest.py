import os

# Deterministic env for unit tests. Set BEFORE app modules import (conftest
# runs first): auth modules read these lazily per call, but tests must never
# depend on the developer's real .env values — hard-assign, don't setdefault.
os.environ["AUTH_SECRET"] = "test-secret-not-for-real-use"
os.environ["INTERNAL_API_SECRET"] = "test-internal-secret"
