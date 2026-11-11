"""Strict multi-tenant boundary enforcement."""

from __future__ import annotations

from uuid import UUID


class TenantIsolationError(PermissionError):
    """Raised whenever an operation attempts cross-tenant access."""


def assert_same_tenant(expected_tenant_id: UUID, actual_tenant_id: UUID, resource: str = "resource") -> None:
    """Fail closed if tenant identifiers do not match."""
    if expected_tenant_id != actual_tenant_id:
        raise TenantIsolationError(
            f"Cross-tenant access denied for {resource}: "
            f"expected {expected_tenant_id}, got {actual_tenant_id}"
        )
