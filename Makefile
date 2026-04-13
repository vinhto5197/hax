# ── Infrastructure ──────────────────────────────────────────────
.PHONY: infra-up infra-down infra-logs infra-ps infra-clean

COMPOSE := docker-compose -f infra/docker-compose/docker-compose.yml

infra-up:
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

# ── Backend (FastAPI) ──────────────────────────────────────────
.PHONY: api

api:
	uvicorn apps.api.main:app --reload --port 8000

# ── Frontend (Next.js) ────────────────────────────────────────
.PHONY: web

web:
	cd apps/web && npm run dev

# ── Setup ─────────────────────────────────────────────────────
.PHONY: setup

setup:
	@bash setup.sh

# ── Dev (infra + api + web) ───────────────────────────────────
.PHONY: dev dev-stop

dev: infra-up
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
