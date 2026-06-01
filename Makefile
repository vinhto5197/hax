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
.PHONY: dev dev-stop

dev: infra-up types
	@echo "Starting API and Web servers..."
	@$(MAKE) -j2 api web

dev-stop:
	@echo "Stopping dev services..."
	@pkill -f "uvicorn apps.api.main:app" || true
	@pkill -f "next dev" || true

# ── Lint ─────────────────────────────────────────────────────
.PHONY: lint

lint:
	ruff check . && ruff format --check .
