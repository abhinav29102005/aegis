.PHONY: setup test test-pg test-cov test-backend test-sdk-ts test-web lint typecheck audit migrate api worker web up down compose-smoke

setup:
	uv sync --python 3.12
	cd packages/sdk-typescript && npm install --no-audit --no-fund
	cd apps/web && npm install --no-audit --no-fund

test: test-backend test-sdk-ts test-web

test-pg:
	AEGIS_TEST_POSTGRES_URL=$${AEGIS_TEST_POSTGRES_URL:-postgresql+psycopg://aegis:aegis_dev_password@127.0.0.1:5432/aegis_platform} uv run pytest -v

test-cov:
	uv run pytest -v --cov=packages --cov=modules --cov=services --cov-report=term-missing

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

audit:
	uv export --frozen --no-emit-workspace --no-hashes -o /tmp/aegis-reqs.txt && uv run pip-audit -r /tmp/aegis-reqs.txt --desc
	cd packages/sdk-typescript && npm audit --omit=dev
	cd apps/web && npm audit --omit=dev

migrate:
	cd packages/database && uv run alembic upgrade head

api:
	uv run uvicorn aegis_api.app:get_default_app --factory --host 0.0.0.0 --port $${API_PORT:-8000}

worker:
	uv run python -m aegis_worker.main

web:
	cd apps/web && npm run dev

up:
	docker compose up -d postgres redis migrate api worker web

down:
	docker compose down

compose-smoke:
	docker compose up -d --build postgres redis migrate api worker web
	@for i in $$(seq 1 30); do \
		if curl -sf "http://127.0.0.1:$${API_PORT:-8000}/ready"; then \
			echo ""; \
			break; \
		fi; \
		if [ "$$i" -eq 30 ]; then \
			docker compose logs api migrate postgres; \
			docker compose down -v --remove-orphans; \
			exit 1; \
		fi; \
		sleep 2; \
	done
	docker compose exec -T worker python -m aegis_worker.main --healthcheck
	@for i in $$(seq 1 30); do \
		if curl -sf "http://127.0.0.1:$${WEB_PORT:-3005}/login" >/dev/null; then \
			break; \
		fi; \
		if [ "$$i" -eq 30 ]; then \
			docker compose logs web api migrate postgres; \
			docker compose down -v --remove-orphans; \
			exit 1; \
		fi; \
		sleep 2; \
	done
	@AUTH_CODE=$$(curl -s -o /tmp/aegis-auth-me.json -w "%{http_code}" "http://127.0.0.1:$${WEB_PORT:-3005}/api/auth/me"); \
	if [ "$$AUTH_CODE" != "401" ] || ! grep -q "UNAUTHENTICATED" /tmp/aegis-auth-me.json; then \
		echo "Unexpected /api/auth/me response: HTTP $$AUTH_CODE $$(cat /tmp/aegis-auth-me.json)"; \
		docker compose logs web api; \
		docker compose down -v --remove-orphans; \
		exit 1; \
	fi
	@rm -f /tmp/aegis-auth-me.json
	docker compose down -v --remove-orphans
