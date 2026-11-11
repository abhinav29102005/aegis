.PHONY: setup test test-packages test-disputeos lint schemas migrate up down

setup:
	uv sync --python 3.12

test: test-packages test-disputeos

test-packages:
	uv run pytest packages/contracts/tests packages/security/tests packages/database/tests packages/paypal/tests -v

test-disputeos:
	PYTHONPATH=modules/disputeos uv run pytest modules/disputeos/tests -v

lint:
	uv run ruff check packages modules/disputeos

schemas:
	uv run python packages/contracts/contracts/export_schemas.py

migrate:
	cd packages/database && uv run alembic upgrade head

up:
	docker compose up -d postgres

down:
	docker compose down

