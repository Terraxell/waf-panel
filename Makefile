# waf-panel — daily-loop targets.
# WHY: a Makefile gives one canonical place where the project's verbs live.
#      docker compose flags drift between developers; a target is a contract.

SHELL := /bin/bash
COMPOSE := docker compose
PROJECT := waf-panel

.PHONY: help up down restart logs ps smoke test lint migrate migrate-revision \
        backend-shell ch-shell pg-shell nuke train train-register \
        ml-test ml-lint ml-svc-test ml-svc-lint ml-svc-shell ml-promote drift-check \
        vendor-ml rebuild-ml-service ch-migrate bootstrap

help: ## Show this help
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

vendor-ml: ## Sync ml/src/waf_ml -> ml-service/waf_ml (build-time vendor; not committed)
	@# WHY: ml-service/Dockerfile expects ./waf_ml/ next to itself.
	@# We don't commit the copy — every up/build re-syncs from ml/.
	@rm -rf ml-service/waf_ml
	@cp -r ml/src/waf_ml ml-service/waf_ml
	@echo "vendored waf_ml -> ml-service/waf_ml"

up: vendor-ml ## Bring the stack up in the background
	$(COMPOSE) up -d --build
	@echo "stack is starting; run 'make smoke' once 'make ps' shows everything healthy"

rebuild-ml-service: vendor-ml ## Force no-cache rebuild of ml-service alone
	$(COMPOSE) build --no-cache ml-service
	$(COMPOSE) up -d ml-service

down: ## Stop the stack, keep volumes
	$(COMPOSE) down

restart: down vendor-ml ## Restart from scratch without dropping volumes
	$(COMPOSE) up -d --build

ps: ## Compose process status
	$(COMPOSE) ps

logs: ## Tail combined logs
	$(COMPOSE) logs -f --tail=200

smoke: ## End-to-end smoke check against the local stack
	@bash scripts/smoke.sh

test: ## Run backend unit tests
	cd backend && python -m pytest -q

lint: ## Run linters across backend
	cd backend && ruff check src tests

migrate: ## Apply alembic migrations to the running stack
	$(COMPOSE) exec backend alembic upgrade head

ch-migrate: ## Re-apply ClickHouse init.sql idempotently (fix)
	@# WHY: ClickHouse's docker-entrypoint runs *.sql once on first volume init.
	@# When init.sql changes after that, the running CH never picks it up.
	@# Every CREATE in init.sql is `IF NOT EXISTS`, so re-running is safe.
	docker cp infra/clickhouse/init.sql waf-clickhouse:/tmp/init.sql
	$(COMPOSE) exec clickhouse clickhouse-client \
		--user waf --password waf_dev_only \
		--multiquery --queries-file=/tmp/init.sql
	@echo "ClickHouse migrations applied."

bootstrap: migrate ch-migrate ## First-time stack setup (this release: schema + CH views + admin)
	@echo "Bootstrap complete. Login at http://localhost:3000 — admin@example.com / admin"

migrate-revision: ## Create a new alembic revision (pass MSG="…")
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(MSG)"

backend-shell: ## Drop into a shell in the backend container
	$(COMPOSE) exec backend /bin/bash

ch-shell: ## ClickHouse client connected to the project DB
	$(COMPOSE) exec clickhouse clickhouse-client --user $$CH_USER --password $$CH_PASSWORD -d $$CH_DB

pg-shell: ## psql shell connected to the project DB
	$(COMPOSE) exec postgres psql -U $$POSTGRES_USER -d $$POSTGRES_DB

nuke: ## Stop and DROP all volumes — dev only, irreversible
	$(COMPOSE) down -v
	rm -rf volumes/

# ── ML pipeline (future release) ────────────────────────────────────────────
# WHY: keeps the trainer command-line in one place; CI just runs `make train`.
#      Postgres registration only fires when --register or --activate is set,
#      so the default invocation is safe to run with the stack down.
ML_DIR    := ml
ML_PY     := python
ML_DATASET := synthetic

train: ## Train LR + XGBoost + IsolationForest on $(ML_DATASET); writes ml/models/<version>/
	cd $(ML_DIR) && $(ML_PY) -m waf_ml.train --dataset $(ML_DATASET)

train-register: ## Train and register all models in Postgres; mark XGBoost active
	cd $(ML_DIR) && $(ML_PY) -m waf_ml.train --dataset $(ML_DATASET) --register --activate xgboos