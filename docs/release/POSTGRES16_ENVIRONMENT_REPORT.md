# PostgreSQL 16 Environment Gate Report

- **Target Release:** AEGIS RC1 (`fix/rc1-guardian-deadlock`, baseline HEAD `5c95e76`, remediation commit `377e52e`)
- **Host OS:** Windows
- **Environment Gate Status:** `BLOCKED` (PostgreSQL 16 unavailable on local host; local installation of PostgreSQL or Docker avoided per release policy)

## 1. Local PostgreSQL 16 Availability Checks

| Check | Result | Outcome |
| --- | --- | --- |
| `DATABASE_URL` / `.env` | `DATABASE_URL` unset; no `.env` file present | Unavailable |
| Local CLI / Container runtime | `psql`, `pg_isready`, and `docker` not found on `PATH` | Unavailable |
| TCP probe `127.0.0.1:5432` | Connection failed | Unavailable |
| Local port listeners (`5432`, `5433`, `5434`, `55432`, `55444`) | No listening sockets | Unavailable |
| WSL distro `Ubuntu` | `Stopped` | Unavailable |

**Conclusion:** Live PostgreSQL 16 verification could not be executed locally and remains `NOT VERIFIED` / `BLOCKED`.

## 2. Observed Runtime Stack Versions

- SQLAlchemy: `2.1.8`
- Pydantic: `2.14.3`
- psycopg: `3.3.8`
- sqlite3: `3.45.3`
- FastAPI: `0.162.4`
- Alembic head revision: `0003_prod_hardening`

## 3. CI Workflow PostgreSQL 16 Configuration & Fix

Inspection of `.github/workflows/ci.yml` established:

1. CI provisions a `postgres:16-alpine` service on `localhost:5432` with database `aegis_test` (`aegis:aegis_test_password@localhost:5432/aegis_test`).
2. `Verify Alembic migrations against PostgreSQL 16` sets `DATABASE_URL=postgresql+psycopg://aegis:aegis_test_password@localhost:5432/aegis_test` and runs `uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head`.
3. `Run full Python & PostgreSQL test suite with coverage` sets `AEGIS_TEST_POSTGRES_URL=postgresql+psycopg://aegis:aegis_test_password@localhost:5432/aegis_test` and `REDIS_URL=redis://localhost:6379/0`.
4. **Configuration Gap Found & Fixed:** Previously, the fixtures in `tests/concurrency/test_rc1_deadlock_stress.py`, `tests/concurrency/test_rc1_financial_invariants.py`, and `tests/concurrency/test_concurrency_harness.py` only checked `os.getenv("DATABASE_URL")`. Under `.github/workflows/ci.yml`, `pytest` receives `AEGIS_TEST_POSTGRES_URL` rather than `DATABASE_URL`, which would have caused the CI concurrency suite to silently fall back to SQLite. All three fixtures were updated to resolve `os.getenv("DATABASE_URL") or os.getenv("AEGIS_TEST_POSTGRES_URL")`.

## 4. Required Unblock Command (When PG16 Is Available)

```bash
export DATABASE_URL="postgresql+psycopg://aegis:aegis_test_password@localhost:5432/aegis_test"
export AEGIS_TEST_POSTGRES_URL="$DATABASE_URL"
cd packages/database && uv run alembic upgrade head && cd ../..
uv run pytest -v packages/database/tests/test_database.py -k postgres
uv run pytest -v tests/concurrency/
```

