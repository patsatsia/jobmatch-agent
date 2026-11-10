# Load .env if it exists, so POSTGRES_* values are available here.
-include .env
export

POSTGRES_USER ?= jobmatch
POSTGRES_DB   ?= jobmatch

UV      := uv run
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help install run up down stop restart logs ps db-shell db-reset \
        migrate migration downgrade migrate-check \
        lint format typecheck test test-unit cov check full clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------- Setup ----------
install: ## Install all dependencies (incl. dev) and pre-commit hooks
	uv sync
	$(UV) pre-commit install

# ---------- App ----------
run: ## Run the API locally with hot reload (needs `make up`)
	$(UV) uvicorn app.main:app --reload

# ---------- Docker ----------
up: ## Start the database in the background
	$(COMPOSE) up -d

down: ## Stop and remove containers (keeps data)
	$(COMPOSE) down

stop: ## Stop containers without removing them
	$(COMPOSE) stop

restart: down up ## Restart containers

logs: ## Follow database logs
	$(COMPOSE) logs -f db

ps: ## Show container status
	$(COMPOSE) ps

db-shell: ## Open psql inside the database container
	$(COMPOSE) exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-reset: ## DANGER: delete all data, recreate the DB and run migrations
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait
	$(UV) alembic upgrade head

full: ## Build the image and run the full stack (db + migrations + api)
	$(COMPOSE) --profile full up --build

# ---------- Migrations ----------
migrate: ## Apply all migrations
	$(UV) alembic upgrade head

migration: ## Create a migration: make migration m="add jobs table"
	@test -n "$(m)" || (echo 'Usage: make migration m="describe the change"' && exit 1)
	$(UV) alembic revision --autogenerate -m "$(m)"

downgrade: ## Roll back the last migration
	$(UV) alembic downgrade -1

migrate-check: ## Check that downgrade and upgrade both work
	$(UV) alembic downgrade -1
	$(UV) alembic upgrade head

# ---------- Quality ----------
lint: ## Lint with ruff
	$(UV) ruff check .

format: ## Auto-fix lint issues and format code
	$(UV) ruff check --fix .
	$(UV) ruff format .

typecheck: ## Type-check with mypy
	$(UV) mypy

test: ## Run all tests (needs `make up`)
	$(UV) pytest

test-unit: ## Run only fast tests (no database)
	$(UV) pytest -m "not integration"

cov: ## Run all tests with a coverage report
	$(UV) pytest --cov --cov-report=term-missing

check: ## Everything CI runs: lint, format check, types, tests
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy
	$(UV) pytest

# ---------- Housekeeping ----------
clean: ## Remove caches and coverage files
	rm -rf .mypy_cache .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +