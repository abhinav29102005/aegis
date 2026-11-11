"""Unified FastAPI application factory for AEGIS."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from database import (
    LocalObjectStorage,
    create_db_engine,
    create_session_factory,
    init_db,
)
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ghostpay.api.router import create_ghostpay_router
from paypal import PayPalSandboxClient
from security import (
    AuthenticationError,
    AuthorizationError,
    NexusSettings,
    TenantIsolationError,
    get_settings,
)
from sqlalchemy import Engine, text

from aegis_api.deps import get_ghostpay_repo, require_tenant_id
from aegis_api.logging_config import configure_logging, correlation_id_var
from aegis_api.rate_limit import SlidingWindowRateLimiterMiddleware
from aegis_api.routers import auth_orgs, disputeos_db, guardian_db, overview, webhooks

logger = logging.getLogger("aegis.api")


def create_app(
    *,
    settings: NexusSettings | None = None,
    engine: Engine | None = None,
    paypal_client: PayPalSandboxClient | None = None,
    create_tables: bool = False,
) -> FastAPI:
    """Create and configure the unified AEGIS FastAPI application."""
    cfg = settings or get_settings()
    cfg.validate_security_posture()
    configure_logging(cfg.log_level)

    db_engine = engine or create_db_engine(cfg.database_url)
    if create_tables:
        init_db(db_engine)
    session_factory = create_session_factory(db_engine)
    storage = LocalObjectStorage(cfg.evidence_storage_dir)
    pp_client = paypal_client or PayPalSandboxClient(settings=cfg)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if cfg.database_url.startswith("sqlite"):
            init_db(db_engine)
        yield
        if engine is None:
            db_engine.dispose()

    app = FastAPI(
        title="AEGIS — Agentic Enforcement, Governance and Investigation System",
        version="1.0.0",
        description="The Financial Black Box for AI Agents: Deterministic spending governance, forensic replay, and dispute investigation.",
        lifespan=lifespan,
    )

    app.state.settings = cfg
    app.state.engine = db_engine
    app.state.session_factory = session_factory
    app.state.object_storage = storage
    app.state.paypal_client = pp_client

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SlidingWindowRateLimiterMiddleware,
        requests_per_minute=cfg.rate_limit_rpm,
    )

    @app.middleware("http")
    async def correlation_and_logging_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        corr_id = request.headers.get("X-Correlation-Id") or str(uuid4())
        token = correlation_id_var.set(corr_id)
        request.state.correlation_id = corr_id
        try:
            response = await call_next(request)
            response.headers["X-Correlation-Id"] = corr_id
            logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
            return response
        finally:
            correlation_id_var.reset(token)

    @app.exception_handler(AuthenticationError)
    async def _auth_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error_code": "AUTHENTICATION_FAILED",
                "message": str(exc),
                "correlation_id": getattr(request.state, "correlation_id", "-"),
            },
        )

    @app.exception_handler(AuthorizationError)
    async def _authz_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error_code": "PERMISSION_DENIED",
                "message": str(exc),
                "correlation_id": getattr(request.state, "correlation_id", "-"),
            },
        )

    @app.exception_handler(TenantIsolationError)
    async def _tenant_error_handler(request: Request, exc: TenantIsolationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error_code": "TENANT_ISOLATION_VIOLATION",
                "message": str(exc),
                "correlation_id": getattr(request.state, "correlation_id", "-"),
            },
        )

    @app.get("/health", tags=["platform"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "aegis-api", "env": cfg.app_env}

    @app.get("/ready", tags=["platform"])
    def readiness() -> dict[str, Any]:
        try:
            with db_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "ready", "database": "connected", "paypal_configured": cfg.paypal_configured}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error_code": "DB_UNAVAILABLE", "message": str(exc)},
            ) from exc

    ghostpay_router = create_ghostpay_router(
        tenant_resolver=require_tenant_id,
        repo_resolver=get_ghostpay_repo,
    )

    app.include_router(auth_orgs.router, prefix="/v1")
    app.include_router(overview.router, prefix="/v1")
    app.include_router(guardian_db.router, prefix="/v1")
    app.include_router(ghostpay_router, prefix="/v1")
    app.include_router(disputeos_db.router, prefix="/v1")
    app.include_router(webhooks.router, prefix="/v1")

    return app


def get_default_app() -> FastAPI:
    return create_app()
