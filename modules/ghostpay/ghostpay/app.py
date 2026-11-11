"""Authenticated, stateless GhostPay deployment entry point."""

import json
import os
from pathlib import Path
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from contracts.fixtures import build_authorized_39_purchase_fixture
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse

from ghostpay.api.router import _resolve_tenant_id, create_ghostpay_router
from ghostpay.replay import ReplayEngine
from ghostpay.snapshots import SnapshotDirectory


class BodyLimit:
    """Bound actual streamed bytes before JSON parsing, not just Content-Length."""

    def __init__(self, app, limit: int = 2_097_152):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                response = JSONResponse(
                    {"detail": "Request body too large"}, status_code=413
                )
                return await response(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {
                "type": "http.request",
                "body": b"".join(chunks),
                "more_body": False,
            }

        await self.app(scope, buffered_receive, send)


def create_app(tokens: dict[str, str] | None = None) -> FastAPI:
    """Create a fail-closed service; each secret token authorizes exactly one tenant."""
    try:
        configured = (
            tokens
            if tokens is not None
            else json.loads(os.environ.get("GHOSTPAY_TOKENS", "{}"))
        )
        if not isinstance(configured, dict) or not configured:
            raise ValueError
        credentials = []
        for token, tenant in configured.items():
            if (
                not isinstance(token, str)
                or len(token) < 32
                or not token.isascii()
                or token.strip() != token
            ):
                raise ValueError
            credentials.append((token, UUID(str(tenant))))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            "Configure GHOSTPAY_TOKENS as a nonempty JSON token-to-tenant map; tokens need 32+ ASCII characters"
        ) from exc

    app = FastAPI(
        title="GhostPay",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(BodyLimit)

    def authenticated_tenant(
        authorization: Annotated[str | None, Header()] = None,
    ) -> UUID:
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() == "bearer" and supplied.isascii():
            for expected, tenant in credentials:
                if compare_digest(supplied, expected):
                    return tenant
        raise HTTPException(
            401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        )

    app.dependency_overrides[_resolve_tenant_id] = authenticated_tenant
    app.include_router(create_ghostpay_router(), prefix="/v1")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok", "service": "ghostpay", "mode": "read-only"}

    @app.get("/v1/ghostpay/example")
    def example(tenant: Annotated[UUID, Depends(authenticated_tenant)]):
        record = build_authorized_39_purchase_fixture()["replay_request"]
        if tenant != record.tenant_id:
            raise HTTPException(
                403, "Example is available only to the synthetic demo tenant"
            )
        return {"source": "SYNTHETIC", "request": record.model_dump(mode="json")}

    directory = os.environ.get("GHOSTPAY_SNAPSHOT_DIR")
    source = SnapshotDirectory(Path(directory)) if directory else None

    @app.get("/v1/ghostpay/payments/{payment_id}/replay")
    def replay_stored(
        payment_id: UUID, tenant: Annotated[UUID, Depends(authenticated_tenant)]
    ):
        if source is None:
            raise HTTPException(503, "Historical snapshot source is not configured")
        try:
            record = source.load(tenant, payment_id)
            if record is None:
                raise HTTPException(404, "Snapshot not found")
            return ReplayEngine.replay(record)
        except (ValueError, PermissionError, OSError) as exc:
            raise HTTPException(422, "Stored snapshot cannot be replayed") from exc

    web = Path(__file__).parent / "web"

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (web / "index.html").read_text()

    @app.get("/app.js")
    def javascript():
        from fastapi.responses import Response

        return Response((web / "app.js").read_text(), media_type="text/javascript")

    @app.get("/app.css")
    def stylesheet():
        from fastapi.responses import Response

        return Response((web / "app.css").read_text(), media_type="text/css")

    return app
