# FlashTix local workflow. `make help` lists every target.
# MONOLITH=1 runs the same code as one process instead of three services:
#   MONOLITH=1 make up / down / logs / ps   (use the same MONOLITH value for every target)

COMPOSE := docker compose$(if $(MONOLITH), -f docker-compose.yml -f docker-compose.monolith.yml)
VENV    := .venv
# Interpreter for `make dev`: containers and CI run 3.12, so prefer it when installed.
PYTHON  ?= $(shell command -v python3.12 || command -v python3.13 || command -v python3)
PY      ?= $(VENV)/bin/python

.DEFAULT_GOAL := help
.PHONY: help dev keys up down clean logs ps psql db-check gateway-check report seed smoke oversell fe-dev test lint fmt

help: ## List targets
	@grep -E '^[a-z.-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

dev: ## Create .venv with the shared library, ruff and pytest
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements-dev.txt

keys: ## Generate local JWT RS256 keys into secrets/
	./scripts/gen-keys.sh

.env:
	cp .env.example .env

up: keys .env ## Build and start the stack, wait until healthy (gateway on http://localhost:8080)
	$(COMPOSE) up --build -d --wait

down: ## Stop the stack
	$(COMPOSE) down

clean: ## Stop the stack and delete its volumes
	$(COMPOSE) down -v

logs: ## Follow logs: make logs s=booking-service
	$(COMPOSE) logs -f $(s)

ps: ## List containers
	$(COMPOSE) ps

psql: ## Open psql as superuser: make psql db=bookingdb
	$(COMPOSE) exec postgres psql -U postgres -d $(or $(db),postgres)

db-check: ## Verify DB owners, per-service isolation and the read-only report role
	./scripts/check-db-setup.sh

gateway-check: ## Verify gateway routing, request ids and the booking rate limit (:8080)
	./scripts/check-gateway.sh

report: ## Write the daily sales report: make report [date=YYYY-MM-DD] (default: yesterday)
	@curl -s --fail-with-body -X POST "http://127.0.0.1:8091/reports/daily$(if $(date),?date=$(date))" && echo

seed: ## Create the demo events (idempotent) and re-arm the flash sale to open in 2 minutes
	@python3 scripts/seed.py

smoke: ## End-to-end check: holds, purchase, ticket PDF, 20-buyer race, oversell check
	@python3 scripts/smoke_test.py

oversell: ## No seat sold twice, sold <= capacity; strict=1 (after load tests) fails on unknown events
	@python3 scripts/check_oversell.py $(if $(strict),--strict)

fe-dev: ## Vite dev server on http://localhost:5173 (proxies /api to the gateway on :8080)
	cd frontend && npm install && npm run dev

test: ## Run all Python tests
	$(PY) -m pytest

lint: ## Lint and check formatting
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt: ## Auto-fix lint issues and format
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .
