.PHONY: setup test test-backend test-sdk-ts test-web lint typecheck migrate api worker web up down

setup:
	uv sync --python 3.12
	cd packages/sdk-typescript && npm install --no-audit --no-fund
	cd apps/web && npm install --no-audit --no-fund

test: test-backend test-sdk-ts test-web

test-backend:
	uv run pytest -v

test-sdk-ts:
	cd packages/sdk-typescript && npm run typecheck && npm test

test-web:
	cd apps/web && npm run typecheck && npm run lint && npm test && npm run build

lint:
	uv run ruff check packages modules services

typecheck:
	cd packages/sdk-typescript && npm run typecheck
	cd apps/web && npm run typecheck

migrate:
	cd packages/database && uv run alembic upgrade head

api:
	uv run uvicorn aegis_api.app:get_default_app --factory --host 0.0.0.0 --port $${API_PORT:-8000}

worker:
	uv run python -m aegis_worker.main

web:
	cd apps/web && npm run dev

up:
	docker compose up -d postgres migrate api worker web

down:
	docker compose down
