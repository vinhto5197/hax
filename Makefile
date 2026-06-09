# ── Infrastructure ──────────────────────────────────────────────
.PHONY: infra-up infra-down infra-logs infra-ps infra-clean infra-psql infra-redis-cli infra-verify

COMPOSE := docker-compose -f infra/docker-compose/docker-compose.yml

infra-up:
	@docker info >/dev/null 2>&1 || { \
	  echo "Docker daemon not reachable. Start your runtime first:"; \
	  echo "  colima start    # if you use Colima"; \
	  echo "  open -a Docker  # if you use Docker Desktop"; \
	  exit 1; \
	}
	$(COMPOSE) up -d

infra-down:
	$(COMPOSE) down

infra-logs:
	$(COMPOSE) logs -f

infra-ps:
	$(COMPOSE) ps

# Tear down containers AND delete volumes (full reset)
infra-clean:
	$(COMPOSE) down -v

infra-psql:
	docker exec -it hax-postgres psql -U hax -d hax

infra-redis-cli:
	docker exec -it hax-redis redis-cli

infra-verify:
	@bash infra/docker-compose/verify.sh

# ── Database (migrations) ──────────────────────────────────────
.PHONY: migrate migrate-down migration

# Apply all pending migrations. Idempotent: no-ops if already at head.
# Requires Postgres up (make infra-up).
migrate:
	.venv/bin/alembic upgrade head

# Roll back the most recent migration.
migrate-down:
	.venv/bin/alembic downgrade -1

# Autogenerate a migration from model changes: make migration m="add x table".
# Review the generated file before committing — autogenerate isn't authoritative.
migration:
	@test -n "$(m)" || { echo 'Usage: make migration m="describe the change"'; exit 1; }
	.venv/bin/alembic revision --autogenerate -m "$(m)"

# ── Backend (FastAPI) ──────────────────────────────────────────
.PHONY: api

api:
	uvicorn apps.api.main:app --reload --port 8000

# ── Frontend (Next.js) ────────────────────────────────────────
.PHONY: web

web:
	cd apps/web && npm run dev

# ── Types (OpenAPI → TypeScript) ───────────────────────────────
.PHONY: types

# Regenerate the frontend's API types from the OpenAPI spec. Offline: dumps
# the spec via app.openapi() (no running server needed), then runs
# openapi-typescript. Also a prerequisite of `make dev`, so types stay synced.
types:
	.venv/bin/python -m apps.api.utils.export_openapi
	cd apps/web && npm run generate:types

# ── Setup ─────────────────────────────────────────────────────
.PHONY: setup sync sync-web

setup:
	@bash setup.sh

# Re-sync python deps with pyproject.toml (after editing dependencies).
sync:
	.venv/bin/pip install -e ".[dev]"

# Re-sync web deps with package.json (after editing dependencies).
sync-web:
	cd apps/web && npm install

# ── Dev (infra + api + web) ───────────────────────────────────
.PHONY: dev dev-stop debug

dev: infra-up types
	@echo "Starting API and Web servers..."
	@$(MAKE) -j2 api web

dev-stop:
	@echo "Stopping dev services..."
	@pkill -f "uvicorn apps.api.main:app" || true
	@pkill -f "next dev" || true

# Like `make dev` but WITHOUT the API: the VS Code debugger (F5, see
# .vscode/launch.json) launches uvicorn itself, so :8000 must stay free.
# Starts infra + web only. Run `make migrate` first if the schema isn't applied.
debug: infra-up types
	@echo "Infra up, types generated. Starting Next on :3000 (leaving :8000 for the debugger)."
	@echo "In VS Code: Run & Debug -> 'Full stack (API + Web)' -> F5 to launch the API + Chrome under the debugger."
	@$(MAKE) web

# ── Status ────────────────────────────────────────────────────
.PHONY: status

# Show whether each service answers on its port. Uses a TCP connect probe
# (nc -z) rather than lsof: lsof only sees host-process listeners, not
# Colima/Docker port-forwarded ones, so it reports false "down" for postgres/redis.
status:
	@printf "%-10s %-6s %s\n" "service" "port" "status"
	@printf "%-10s %-6s %s\n" "-------" "----" "------"
	@for svc in "postgres 5432" "redis 6379" "api 8000" "web 3000"; do \
	  set -- $$svc; name=$$1; port=$$2; \
	  if nc -z -G1 localhost $$port >/dev/null 2>&1; then st="UP"; else st="down"; fi; \
	  printf "%-10s %-6s %s\n" "$$name" "$$port" "$$st"; \
	done

# ── Lint ─────────────────────────────────────────────────────
.PHONY: lint

lint:
	ruff check . && ruff format --check .
