#!/usr/bin/env bash
# End-to-end check that local postgres + redis are wired up correctly.
# Starts with `make infra-clean`, which wipes named volumes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

step() { echo; echo "==> $1"; }
ok()   { echo "    ok: $1"; }
fail() { echo "    FAIL: $1" >&2; exit 1; }

wait_healthy() {
  local name="$1" deadline=$((SECONDS + 60))
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null)" = "healthy" ]; do
    [ "$SECONDS" -lt "$deadline" ] || fail "$name never reached healthy in 60s"
    sleep 1
  done
}

step "1/8 infra-clean"
make infra-clean >/dev/null
ok "clean state"

step "2/8 infra-up"
make infra-up >/dev/null
ok "containers started"

step "3/8 wait for healthy"
wait_healthy hax-postgres
wait_healthy hax-redis
ok "both containers healthy"

step "4/8 pgvector extension loaded"
docker exec hax-postgres psql -U hax -d hax -tAc \
  "SELECT 1 FROM pg_extension WHERE extname='vector'" \
  | grep -q '^1$' || fail "vector extension not loaded"
ok "vector extension present"

step "5/8 redis ping"
[ "$(docker exec hax-redis redis-cli PING)" = "PONG" ] || fail "redis did not respond PONG"
ok "redis responded PONG"

step "6/8 host-side connection via venv sqlalchemy (asyncpg, same driver as the app)"
.venv/bin/python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def check():
    e = create_async_engine('postgresql+asyncpg://hax:hax@localhost:5432/hax')
    async with e.connect() as c:
        assert (await c.execute(text('SELECT 1'))).scalar() == 1
    await e.dispose()

asyncio.run(check())
" || fail "host could not reach postgres on localhost:5432"
ok "host->postgres conn ok"

step "7/8 volume persistence across restart"
docker exec hax-postgres psql -U hax -d hax -c \
  "CREATE TABLE _probe (x int); INSERT INTO _probe VALUES (42);" >/dev/null
make infra-down >/dev/null
make infra-up >/dev/null
wait_healthy hax-postgres
got="$(docker exec hax-postgres psql -U hax -d hax -tAc 'SELECT x FROM _probe;')"
[ "$got" = "42" ] || fail "probe row did not survive restart (got: '$got')"
docker exec hax-postgres psql -U hax -d hax -c "DROP TABLE _probe;" >/dev/null
ok "row survived restart"

step "8/8 leave clean"
make infra-down >/dev/null
ok "containers down, volumes kept"

echo
echo "infra verify: all 8 steps passed"
echo
echo "NOTE: step 1 wiped all volumes (fresh-boot check). The database is EMPTY:"
echo "  make infra-up && make migrate   # restore schema before running the app"
