# Core SaaS scaffold: developer commands (dev_tools.md "Make targets").
# Run `make help` for the list.

SHELL := /bin/bash
COMPOSE := docker compose

# Host ports used by `make check`. Precedence: exported env var > .env > default.
# .env is deliberately NOT `include`d: make would keep the spaces before inline
# "# comments" and, for variables that also exist in the environment, export
# the padded value to docker compose ("invalid hostPort: 5200   "). Instead we
# read just the value token for each key.
envval = $(or $(shell sed -n 's/^$(1)=\([^[:space:]#]*\).*/\1/p' .env 2>/dev/null | tail -n1),$(2))
FRONTEND_PORT ?= $(call envval,FRONTEND_PORT,3200)
BACKEND_PORT ?= $(call envval,BACKEND_PORT,8200)
MAILPIT_UI_PORT ?= $(call envval,MAILPIT_UI_PORT,8025)
S3_API_PORT ?= $(call envval,S3_API_PORT,9000)
S3_CONSOLE_PORT ?= $(call envval,S3_CONSOLE_PORT,9201)
POSTGRES_HOST_PORT ?= $(call envval,POSTGRES_HOST_PORT,5200)
MAILPIT_SMTP_PORT ?= $(call envval,MAILPIT_SMTP_PORT,1025)

.DEFAULT_GOAL := help
.PHONY: help env up down build logs ps check lint test test-setup test-unit clean \
        migrate create-tenant list-orgs cli gen-client gen-client-check e2e \
        fe-install fe-lint fe-format fe-test fe-build fe-rebuild ports audit perf

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example (never overwrites)
	@if [ -f .env ]; then echo ".env already exists, left unchanged"; \
	 else cp .env.example .env && echo "created .env from .env.example"; fi

up: env ## Start the dev stack in the background
	$(COMPOSE) up -d

down: ## Stop the dev stack (keeps data volumes)
	$(COMPOSE) down

build: ## Rebuild the backend/worker and frontend images
	$(COMPOSE) build

logs: ## Follow logs of all services (Ctrl+C to stop)
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

check: ## Smoke-check every published endpoint
	@fail=0; \
	for u in "http://localhost:$(BACKEND_PORT)/health/ready" \
	         "http://localhost:$(FRONTEND_PORT)/login" \
	         "http://localhost:$(MAILPIT_UI_PORT)/" \
	         "http://localhost:$(S3_API_PORT)/health" \
	         "http://localhost:$(S3_CONSOLE_PORT)/rustfs/console/"; do \
	  code=$$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$$u"); \
	  if [ "$$code" = "200" ]; then echo "OK   $$code $$u"; else echo "FAIL $$code $$u"; fail=1; fi; \
	done; \
	$(COMPOSE) exec -T postgres pg_isready -q && echo "OK   postgres ready" || { echo "FAIL postgres"; fail=1; }; \
	$(COMPOSE) exec -T redis redis-cli ping | grep -q PONG && echo "OK   redis ping" || { echo "FAIL redis"; fail=1; }; \
	exit $$fail

ports: ## Show whether this clone's host ports are free (several clones on one machine)
	@bash deploy/check_ports.sh \
	  FRONTEND_PORT=$(FRONTEND_PORT):frontend:3200 \
	  BACKEND_PORT=$(BACKEND_PORT):backend:8200 \
	  POSTGRES_HOST_PORT=$(POSTGRES_HOST_PORT):postgres:5432 \
	  S3_API_PORT=$(S3_API_PORT):rustfs:9000 \
	  S3_CONSOLE_PORT=$(S3_CONSOLE_PORT):rustfs:9001 \
	  MAILPIT_SMTP_PORT=$(MAILPIT_SMTP_PORT):mailpit:1025 \
	  MAILPIT_UI_PORT=$(MAILPIT_UI_PORT):mailpit:8025

# Backend tests and lint run on the HOST with uv + testcontainers (B01 D1).
# uv lives in ~/.local/bin; add it to PATH here so make works in any shell.
export PATH := $(HOME)/.local/bin:$(PATH)
UV := cd backend && uv run

test-setup: ## Install backend dev dependencies on the host (uv sync)
	cd backend && uv sync

lint: ## Lint + type-check backend (ruff, pyright); frontend: make fe-lint
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) pyright

test: ## Run backend tests on the host (needs Docker for integration tests)
	$(UV) pytest -q

test-unit: ## Run backend unit tests only (no Docker needed)
	$(UV) pytest -q -m "not integration"

clean: ## Stop the stack AND DELETE all data volumes (asks first)
	@read -p "This deletes Postgres, Redis and RustFS (S3) data. Type 'yes' to continue: " ans; \
	 [ "$$ans" = "yes" ] && $(COMPOSE) down -v || echo "aborted"

# --- Platform administration CLI (B02) ----------------------------------------
# Runs `python -m app.cli` inside the backend container. CLI_USER becomes the
# audit actor ("cli:<you>"). -T (no TTY) unless a password prompt is needed.
CLI := $(COMPOSE) exec -T -e CLI_USER=$(USER) backend python -m app.cli
CLI_TTY := $(COMPOSE) exec -it -e CLI_USER=$(USER) backend python -m app.cli

migrate: ## Run public migrations, then tenant migrations for every org
	$(CLI) migrate-all

create-tenant: ## make create-tenant slug=acme name="Acme" owner=owner@acme.test [password=1]
	@if [ -z "$(slug)" ] || [ -z "$(name)" ] || [ -z "$(owner)" ]; then \
	  echo 'usage: make create-tenant slug=acme name="Acme Inc" owner=owner@acme.test [password=1]'; exit 2; fi
	@if [ "$(password)" = "1" ]; then \
	  $(CLI_TTY) create-tenant --slug "$(slug)" --name "$(name)" --owner-email "$(owner)" --owner-password; \
	else \
	  $(CLI) create-tenant --slug "$(slug)" --name "$(name)" --owner-email "$(owner)"; \
	fi

list-orgs: ## List organizations
	$(CLI) list-orgs

cli: ## Any CLI command: make cli args="suspend-org --slug acme"  (make cli args=--help)
	$(CLI) $(args)

# --- Frontend (B08) -------------------------------------------------------------
# The host has no pnpm / Node 22, so frontend tooling runs in the frontend
# container (B08 D16). `exec` needs the stack up (`make up`); fe-build uses a
# throw-away `run` container so `next build` does not clobber the dev .next.
FE := $(COMPOSE) exec -T frontend pnpm
FE_RUN := $(COMPOSE) run --rm --no-deps -T frontend pnpm

fe-install: ## Install/update frontend deps in the running container (after editing package.json)
	$(FE) install

fe-lint: ## Lint + type-check + format-check the frontend (eslint, tsc, prettier)
	$(FE) lint
	$(FE) typecheck
	$(FE) format:check

fe-format: ## Auto-format the frontend (prettier)
	$(FE) format

fe-test: ## Run frontend unit tests (Vitest + RTL)
	$(FE) test

fe-build: ## Production build of the frontend in a throw-away container
	$(FE_RUN) build

fe-rebuild: ## Rebuild the frontend image AND renew its node_modules volume (after dep changes)
	$(COMPOSE) up -d --build --renew-anon-volumes frontend

# API client generation (B08 D15). The schema is dumped OFFLINE from the app
# (no DB needed) on the host with uv, then orval runs in the frontend container.
GEN_CHECK := frontend/src/api/.gen-check

gen-client: ## Regenerate the frontend API client from the backend OpenAPI schema
	cd backend && uv run python -m app.openapi_dump ../frontend/openapi.json
	$(FE) gen-client
	@echo "client regenerated: frontend/openapi.json + frontend/src/api/generated/"

gen-client-check: ## Fail if the committed API client is out of date with the backend
	@rm -rf $(GEN_CHECK) && mkdir -p $(GEN_CHECK)
	@cd backend && uv run python -m app.openapi_dump ../$(GEN_CHECK)/openapi.json
	@$(COMPOSE) exec -T -e ORVAL_INPUT=./src/api/.gen-check/openapi.json \
	  -e ORVAL_OUTPUT=./src/api/.gen-check frontend pnpm gen-client >/dev/null
	@rc=0; \
	 diff -q frontend/openapi.json $(GEN_CHECK)/openapi.json >/dev/null || { echo "DRIFT: frontend/openapi.json is stale"; rc=1; }; \
	 for d in endpoints model; do \
	   diff -r frontend/src/api/generated/$$d $(GEN_CHECK)/$$d >/dev/null || { echo "DRIFT: src/api/generated/$$d differs"; rc=1; }; \
	 done; \
	 rm -rf $(GEN_CHECK); \
	 if [ $$rc = 0 ]; then echo "OK   generated client is up to date"; else echo "run: make gen-client"; fi; \
	 exit $$rc

# --- Gates and browser tests (B12, B13) ---------------------------------------

# pip-audit has no severity: any finding fails unless listed (with a reason) in
# deploy/audit_ignore.txt. A scan that cannot reach its service fails too.
audit: ## Known vulnerabilities: pip-audit (any) + pnpm audit (high/critical)
	@grep -vE '^[[:space:]]*(#|$$)' deploy/audit_ignore.txt | sed 's/^/accepted: /' || true
	@set -o pipefail; req=$$(mktemp); trap 'rm -f "$$req"' EXIT; \
	 (cd backend && uv export --frozen --no-dev --no-hashes -q > "$$req") && \
	 uvx pip-audit -r "$$req" --no-deps --disable-pip --progress-spinner off \
	   $$(awk '!/^[[:space:]]*(#|$$)/{print "--ignore-vuln", $$1}' deploy/audit_ignore.txt)
	$(FE) audit --audit-level high

perf: ## p95 < 300 ms on list endpoints with 10 000 rows (throwaway tenant)
	$(COMPOSE) exec -T backend python - < backend/tests/perf/list_p95.py

e2e: ## Browser tests of the critical flows C1, C4, C5, C6 (needs the stack up; B12)
	bash frontend/tests/e2e/run_e2e.sh

ci: ## Everything CI runs, locally: lint, tests, frontend checks + build, client drift, audits, e2e
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) fe-lint
	$(MAKE) fe-test
	$(MAKE) fe-build
	$(MAKE) gen-client-check
	$(MAKE) audit
	$(MAKE) e2e

