"""Strict multi-tenant boundary enforcement."""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger("aegis.security.tenant")


class TenantIsolationError(PermissionError):
    """Raised whenever an operation attempts cross-tenant access.

    User-facing error messages intentionally omit tenant UUIDs to prevent
    cross-tenant identifier disclosure; diagnostic UUIDs are stored on
    internal attributes and emitted to server logs.
    """

    def __init__(
        self,
        message: str = "Cross-tenant access denied",
        *,
        resource: str | None = None,
        expected_tenant_id: UUID | None = None,
        actual_tenant_id: UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.resource = resource
        self.expected_tenant_id = expected_tenant_id
        self.actual_tenant_id = actual_tenant_id


def assert_same_tenant(expected_tenant_id: UUID, actual_tenant_id: UUID, resource: str = "resource") -> None:
    """Fail closed if tenant identifiers do not match without leaking tenant UUIDs in message."""
    if expected_tenant_id != actual_tenant_id:
        logger.warning(
            "Cross-tenant access denied for %s (expected=%s, actual=%s)",
            resource,
            expected_tenant_id,
            actual_tenant_id,
        )
        raise TenantIsolationError(
            f"Cross-tenant access denied for {resource}",
            resource=resource,
            expected_tenant_id=expected_tenant_id,
            actual_tenant_id=actual_tenant_id,
        )


validate_tenant_isolation = assert_same_tenant
