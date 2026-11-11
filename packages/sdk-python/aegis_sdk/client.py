"""HTTP client, asynchronous client, webhook verifiers, and non-privileged AI agent middleware for AEGIS."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID, uuid4

import httpx

from aegis_sdk.exceptions import AegisAPIError
from aegis_sdk.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
    paginate,
    paginate_async,
)
from aegis_sdk.webhook import verify_aegis_signature, verify_webhook_signature

RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})


def _build_timeout(timeout: float | httpx.Timeout) -> httpx.Timeout:
    if isinstance(timeout, httpx.Timeout):
        return timeout
    return httpx.Timeout(timeout)


def _handle_response_error(resp: httpx.Response) -> None:
    try:
        err_payload = resp.json()
    except Exception:
        err_payload = resp.text
    raise AegisAPIError.from_response(resp.status_code, err_payload)


class AegisClient:
    """Synchronous typed client for AEGIS REST APIs (`/v1/*`)."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        bearer_token: str | None = None,
        organization_id: str | UUID | None = None,
        timeout: float | httpx.Timeout = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.2,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._bearer_token = bearer_token
        self._organization_id = str(organization_id) if organization_id else None
        self._max_retries = max(0, max_retries)
        self._backoff_factor = backoff_factor
        self._timeout = _build_timeout(timeout)
        self._client = client or httpx.Client(base_url=self.base_url, timeout=self._timeout)
        self._owns_client = client is None

    def __enter__(self) -> AegisClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def set_token(self, bearer_token: str | None) -> None:
        self._bearer_token = bearer_token

    def set_api_key(self, api_key: str | None) -> None:
        self._api_key = api_key

    def set_organization_id(self, organization_id: str | UUID | None) -> None:
        self._organization_id = str(organization_id) if organization_id else None

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"X-Correlation-Id": str(uuid4())}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        elif self._api_key:
            headers["X-API-Key"] = self._api_key
        if self._organization_id:
            headers["X-Org-Id"] = self._organization_id
            headers["X-Tenant-Id"] = self._organization_id
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
        headers: dict[str, str] | None = None,
        raw_bytes: bool = False,
    ) -> Any:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        req_headers = self._headers(headers)
        attempt = 0

        while True:
            try:
                resp = self._client.request(
                    method,
                    path,
                    json=json_body,
                    data=data,
                    files=files,
                    params=clean_params,
                    headers=req_headers,
                )
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                    attempt += 1
                    time.sleep(self._backoff_factor * (2 ** (attempt - 1)))
                    continue

                if resp.status_code >= 400:
                    _handle_response_error(resp)

                if raw_bytes:
                    return resp.content
                if resp.status_code == 204 or not resp.content:
                    return None
                return resp.json()

            except httpx.TransportError as exc:
                if attempt < self._max_retries:
                    attempt += 1
                    time.sleep(self._backoff_factor * (2 ** (attempt - 1)))
                    continue
                raise exc

    # =========================================================================
    # Auth & Sessions
    # =========================================================================
    def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        organization_name: str,
        organization_slug: str,
    ) -> dict[str, Any]:
        res = self._request(
            "POST",
            "/v1/auth/register",
            json_body={
                "email": email,
                "password": password,
                "full_name": full_name,
                "organization_name": organization_name,
                "organization_slug": organization_slug,
            },
        )
        if isinstance(res, dict) and "access_token" in res:
            self.set_token(res["access_token"])
            if "active_tenant_id" in res:
                self.set_organization_id(res["active_tenant_id"])
        return res

    def login(
        self,
        *,
        email: str,
        password: str,
        organization_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"email": email, "password": password}
        if organization_id is not None:
            body["organization_id"] = str(organization_id)
        res = self._request("POST", "/v1/auth/login", json_body=body)
        if isinstance(res, dict) and "access_token" in res:
            self.set_token(res["access_token"])
            if "active_tenant_id" in res:
                self.set_organization_id(res["active_tenant_id"])
        return res

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/v1/auth/me")

    def switch_org(self, organization_id: str | UUID) -> dict[str, Any]:
        self.set_organization_id(organization_id)
        return self.me()

    def list_orgs(self) -> list[dict[str, Any]]:
        info = self.me()
        return info.get("organizations", [])

    def create_org(self, *, name: str, slug: str) -> dict[str, Any]:
        return self._request("POST", "/v1/orgs", json_body={"name": name, "slug": slug})

    def update_current_org(self, *, name: str) -> dict[str, Any]:
        return self._request("PATCH", "/v1/orgs/current", json_body={"name": name})

    def list_members(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/orgs/members")

    def invite_member(
        self,
        *,
        email: str,
        full_name: str = "Workspace Member",
        password: str | None = None,
        role: str = "OPERATOR",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"email": email, "full_name": full_name, "role": role}
        if password is not None:
            body["password"] = password
        return self._request("POST", "/v1/orgs/members", json_body=body)

    def update_member_role(self, user_id: str | UUID, *, role: str) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/orgs/members/{user_id}/role", json_body={"role": role})

    # =========================================================================
    # Guardian: Agents
    # =========================================================================
    def create_agent(
        self,
        *,
        name: str,
        public_fingerprint: str,
        purpose: str = "autonomous-purchasing",
        framework: str = "langgraph",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/guardian/agents",
            json_body={
                "name": name,
                "public_fingerprint": public_fingerprint,
                "purpose": purpose,
                "framework": framework,
            },
        )

    def list_agents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/guardian/agents")

    def get_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        str_id = str(agent_id)
        for agent in self.list_agents():
            if str(agent.get("id")) == str_id:
                return agent
        raise AegisAPIError(404, f"Agent {agent_id} not found")

    def update_agent_status(self, agent_id: str | UUID, status: str) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/guardian/agents/{agent_id}/status", json_body={"status": status})

    def suspend_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        return self.update_agent_status(agent_id, "SUSPENDED")

    def revoke_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        return self.update_agent_status(agent_id, "REVOKED")

    def activate_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        return self.update_agent_status(agent_id, "ACTIVE")

    # =========================================================================
    # Guardian: Merchants
    # =========================================================================
    def create_merchant(
        self,
        *,
        name: str,
        domain: str,
        category: str = "SOFTWARE",
        paypal_merchant_id: str | None = None,
        is_allowlisted: bool = True,
        is_sandbox_verified: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/guardian/merchants",
            json_body={
                "name": name,
                "domain": domain,
                "category": category,
                "paypal_merchant_id": paypal_merchant_id,
                "is_allowlisted": is_allowlisted,
                "is_sandbox_verified": is_sandbox_verified,
            },
        )

    def list_merchants(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/guardian/merchants")

    def get_merchant(self, merchant_id: str | UUID) -> dict[str, Any]:
        str_id = str(merchant_id)
        for m in self.list_merchants():
            if str(m.get("id")) == str_id:
                return m
        raise AegisAPIError(404, f"Merchant {merchant_id} not found")

    def toggle_merchant_allowlist(self, merchant_id: str | UUID, is_allowlisted: bool) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/v1/guardian/merchants/{merchant_id}/allowlist",
            json_body={"is_allowlisted": is_allowlisted},
        )

    # =========================================================================
    # Guardian: Passports
    # =========================================================================
    def create_passport(
        self,
        *,
        agent_id: str | UUID,
        total_budget_minor: int,
        per_tx_limit_minor: int,
        daily_limit_minor: int,
        human_approval_threshold_minor: int = 5000,
        allowed_merchant_ids: list[str | UUID] | None = None,
        allowed_categories: list[str] | None = None,
        allow_unknown_merchants: bool = False,
        currency: str = "USD",
        policy_version: str = "policy-v1",
        expires_in_days: int = 30,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/guardian/passports",
            json_body={
                "agent_id": str(agent_id),
                "total_budget_minor": total_budget_minor,
                "per_tx_limit_minor": per_tx_limit_minor,
                "daily_limit_minor": daily_limit_minor,
                "human_approval_threshold_minor": human_approval_threshold_minor,
                "allowed_merchant_ids": [str(m) for m in (allowed_merchant_ids or [])],
                "allowed_categories": allowed_categories or [],
                "allow_unknown_merchants": allow_unknown_merchants,
                "currency": currency.upper(),
                "policy_version": policy_version,
                "expires_in_days": expires_in_days,
            },
        )

    issue_passport = create_passport

    def list_passports(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/guardian/passports")

    def get_passport(self, passport_id: str | UUID) -> dict[str, Any]:
        str_id = str(passport_id)
        for p in self.list_passports():
            if str(p.get("id")) == str_id:
                return p
        raise AegisAPIError(404, f"Passport {passport_id} not found")

    def update_passport_policy(
        self,
        passport_id: str | UUID,
        *,
        per_tx_limit_minor: int | None = None,
        daily_limit_minor: int | None = None,
        human_approval_threshold_minor: int | None = None,
        allowed_merchant_ids: list[str | UUID] | None = None,
        allowed_categories: list[str] | None = None,
        allow_unknown_merchants: bool | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if per_tx_limit_minor is not None:
            body["per_tx_limit_minor"] = per_tx_limit_minor
        if daily_limit_minor is not None:
            body["daily_limit_minor"] = daily_limit_minor
        if human_approval_threshold_minor is not None:
            body["human_approval_threshold_minor"] = human_approval_threshold_minor
        if allowed_merchant_ids is not None:
            body["allowed_merchant_ids"] = [str(m) for m in allowed_merchant_ids]
        if allowed_categories is not None:
            body["allowed_categories"] = allowed_categories
        if allow_unknown_merchants is not None:
            body["allow_unknown_merchants"] = allow_unknown_merchants
        return self._request("PATCH", f"/v1/guardian/passports/{passport_id}", json_body=body)

    def revoke_passport(self, passport_id: str | UUID) -> dict[str, Any]:
        return self._request("POST", f"/v1/guardian/passports/{passport_id}/revoke")

    # =========================================================================
    # Guardian: Proposals, Payments & Approvals
    # =========================================================================
    def submit_purchase_proposal(
        self,
        *,
        agent_id: str | UUID,
        passport_id: str | UUID,
        merchant_id: str | UUID,
        merchant_name: str,
        merchant_category: str = "SOFTWARE",
        amount_minor: int,
        currency: str = "USD",
        item_summary: str = "",
        rationale: str = "",
        line_items: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
        quote_expires_in_seconds: int = 1800,
    ) -> dict[str, Any]:
        key = idempotency_key or f"sdk-{uuid4().hex[:16]}"
        return self._request(
            "POST",
            "/v1/guardian/proposals",
            json_body={
                "agent_id": str(agent_id),
                "passport_id": str(passport_id),
                "merchant_id": str(merchant_id),
                "merchant_name": merchant_name,
                "merchant_category": merchant_category,
                "amount_minor": amount_minor,
                "currency": currency.upper(),
                "item_summary": item_summary,
                "line_items": line_items or [],
                "rationale": rationale,
                "idempotency_key": key,
                "quote_expires_in_seconds": quote_expires_in_seconds,
            },
        )

    create_proposal = submit_purchase_proposal

    def approve_proposal(
        self,
        intent_id: str | UUID,
        *,
        approver_id: str,
        comment: str | None = None,
        approved: bool = True,
        approval_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        params = {"approval_id": str(approval_id)} if approval_id else None
        return self._request(
            "POST",
            f"/v1/guardian/proposals/{intent_id}/approve",
            params=params,
            json_body={"approver_id": approver_id, "approved": approved, "comment": comment},
        )

    def reject_proposal(
        self,
        intent_id: str | UUID,
        *,
        approver_id: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        return self.approve_proposal(intent_id, approver_id=approver_id, comment=comment, approved=False)

    decide_approval = approve_proposal

    def initiate_checkout(
        self,
        intent_id: str | UUID,
        *,
        attempt_number: int = 1,
        idempotency_key: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/checkout",
            json_body={
                "attempt_number": attempt_number,
                "idempotency_key": idempotency_key,
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        )

    def buyer_approved(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
        payer_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/buyer-approved",
            json_body={"attempt_id": str(attempt_id), "payer_id": payer_id},
        )

    def capture_payment(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/capture",
            json_body={"attempt_id": str(attempt_id)},
        )

    capture = capture_payment

    def buyer_declined(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/buyer-declined",
            json_body={"attempt_id": str(attempt_id), "reason": reason},
        )

    def reconcile_payment(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/reconcile",
            json_body={"attempt_id": str(attempt_id)},
        )

    def get_payment(self, intent_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/guardian/payments/{intent_id}")

    def get_payment_detail(self, intent_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/guardian/payments/{intent_id}/detail")

    def list_payments(
        self,
        *,
        state: str | None = None,
        agent_id: str | UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/v1/guardian/payments",
            params={
                "state": state,
                "agent_id": str(agent_id) if agent_id else None,
                "limit": limit,
                "offset": offset,
            },
        )

    def list_approvals(
        self,
        *,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/v1/guardian/approvals",
            params={"status_filter": status_filter, "limit": limit, "offset": offset},
        )

    def get_approval(self, approval_id: str | UUID) -> dict[str, Any]:
        str_id = str(approval_id)
        for apprv in self.list_approvals():
            if str(apprv.get("id")) == str_id:
                return apprv
        raise AegisAPIError(404, f"Approval {approval_id} not found")

    # =========================================================================
    # GhostPay: Timelines, Replay, Simulations, Agent DNA
    # =========================================================================
    def get_replay_timeline(self, payment_intent_id: str | UUID) -> list[dict[str, Any]]:
        return self._request("GET", f"/v1/ghostpay/timeline/by-payment/{payment_intent_id}")

    def reconstruct_timeline(
        self,
        events: list[dict[str, Any]],
        evidence_records: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return self._request(
            "POST",
            "/v1/ghostpay/timeline",
            json_body={"events": events, "evidence_records": evidence_records or []},
        )

    def get_trace_timeline(self, trace_id: str | UUID) -> list[dict[str, Any]]:
        return self._request("GET", f"/v1/ghostpay/traces/{trace_id}/timeline")

    def create_investigation(
        self,
        trace_id: str | UUID,
        *,
        counterfactual_policies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/ghostpay/investigations",
            json_body={"trace_id": str(trace_id), "counterfactual_policies": counterfactual_policies or []},
        )

    def list_investigations(
        self,
        *,
        payment_intent_id: str | UUID | None = None,
        consistency_status: str | None = None,
        drift_detected: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/ghostpay/investigations",
            params={
                "payment_intent_id": str(payment_intent_id) if payment_intent_id else None,
                "consistency_status": consistency_status,
                "drift_detected": drift_detected,
                "limit": limit,
                "offset": offset,
            },
        )

    def get_investigation(self, investigation_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/ghostpay/investigations/{investigation_id}")

    def get_investigation_evidence(self, investigation_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/ghostpay/investigations/{investigation_id}/evidence")

    def replay_by_payment(
        self,
        intent_id: str | UUID,
        *,
        policy_version: str | None = None,
        persist_investigation: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/ghostpay/replay/by-payment/{intent_id}",
            json_body={"policy_version": policy_version, "persist_investigation": persist_investigation},
        )

    def simulate_by_payment(
        self,
        intent_id: str | UUID,
        *,
        overrides: dict[str, Any],
        policy_version: str | None = None,
        persist_investigation: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/ghostpay/simulate/by-payment/{intent_id}",
            json_body={
                "overrides": overrides,
                "policy_version": policy_version,
                "persist_investigation": persist_investigation,
            },
        )

    def run_counterfactual_simulation(
        self,
        replay_request: dict[str, Any],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/ghostpay/simulate",
            json_body={"request": replay_request, "overrides": overrides},
        )

    simulate = run_counterfactual_simulation

    def compare_policies(
        self,
        replay_request: dict[str, Any],
        policies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/ghostpay/replay/compare",
            json_body={"replay_request": replay_request, "policies": policies},
        )

    def get_agent_profile(self, agent_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/ghostpay/agents/{agent_id}/profile")

    get_profile = get_agent_profile

    def analyze_agent_dna(
        self,
        agent_id: str | UUID,
        *,
        target_trace_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/ghostpay/agents/{agent_id}/analyze",
            json_body={"target_trace_id": str(target_trace_id) if target_trace_id else None},
        )

    def ingest_trace(self, trace_payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/ghostpay/traces/ingest", json_body=trace_payload)

    def get_trace(self, trace_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/ghostpay/traces/{trace_id}")

    # =========================================================================
    # DisputeOS: Cases, Evidence & Reports
    # =========================================================================
    def create_dispute_case(
        self,
        *,
        reason: str,
        buyer_claim: str,
        amount_minor: int,
        currency: str = "USD",
        source_type: str = "MANUAL",
        is_synthetic: bool = False,
        correlation_id: str | UUID | None = None,
        payment_intent_id: str | UUID | None = None,
        evidence_records: list[dict[str, Any]] | None = None,
        paypal_dispute_id: str | None = None,
        case_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "reason": reason,
            "buyer_claim": buyer_claim,
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "source_type": source_type,
            "is_synthetic": is_synthetic,
            "evidence_records": evidence_records or [],
            "paypal_dispute_id": paypal_dispute_id,
        }
        if correlation_id is not None:
            body["correlation_id"] = str(correlation_id)
        if payment_intent_id is not None:
            body["payment_intent_id"] = str(payment_intent_id)
        if case_id is not None:
            body["case_id"] = str(case_id)
        return self._request("POST", "/v1/disputeos/cases", json_body=body)

    def list_dispute_cases(
        self,
        *,
        status_filter: str | None = None,
        is_synthetic: bool | None = None,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/v1/disputeos/cases",
            params={"status_filter": status_filter, "is_synthetic": is_synthetic},
        )

    list_disputes = list_dispute_cases
    list_cases = list_dispute_cases

    def get_dispute_case(self, case_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/disputeos/cases/{case_id}")

    def seed_demo_case(self) -> dict[str, Any]:
        return self._request("POST", "/v1/disputeos/cases/seed-demo")

    def assign_case(self, case_id: str | UUID, assigned_to: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/disputeos/cases/{case_id}/assign",
            json_body={"assigned_to": assigned_to},
        )

    def add_case_note(self, case_id: str | UUID, body: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/disputeos/cases/{case_id}/notes", json_body={"body": body})

    def attach_evidence(
        self,
        case_id: str | UUID,
        *,
        source_type: str,
        source_ref: str,
        title: str,
        content: Any,
        correlation_id: str | UUID | None = None,
        payment_intent_id: str | UUID | None = None,
        is_synthetic: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/disputeos/cases/{case_id}/evidence",
            json_body={
                "source_type": source_type,
                "source_ref": source_ref,
                "title": title,
                "content": content,
                "correlation_id": str(correlation_id) if correlation_id else None,
                "payment_intent_id": str(payment_intent_id) if payment_intent_id else None,
                "is_synthetic": is_synthetic,
            },
        )

    def upload_evidence_artifact(
        self,
        case_id: str | UUID,
        *,
        file_content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        title: str = "Uploaded Evidence Document",
        source_type: str = "DELIVERY_RECEIPT",
    ) -> dict[str, Any]:
        files = {"file": (filename, file_content, content_type)}
        data = {"title": title, "source_type": source_type}
        return self._request("POST", f"/v1/disputeos/cases/{case_id}/artifacts", files=files, data=data)

    def download_evidence_artifact(self, case_id: str | UUID, artifact_id: str | UUID) -> bytes:
        return self._request(
            "GET",
            f"/v1/disputeos/cases/{case_id}/artifacts/{artifact_id}",
            raw_bytes=True,
        )

    def run_case_analysis(self, case_id: str | UUID) -> dict[str, Any]:
        return self._request("POST", f"/v1/disputeos/cases/{case_id}/analyze")

    run_analysis = run_case_analysis

    def get_case_report(self, case_id: str | UUID) -> dict[str, Any]:
        return self._request("GET", f"/v1/disputeos/cases/{case_id}/report")

    get_analysis = get_case_report
    generate_report = get_case_report

    def approve_case(
        self,
        case_id: str | UUID,
        *,
        approver_id: str | None = None,
        draft_response_text: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if approver_id is not None:
            body["approver_id"] = approver_id
        if draft_response_text is not None:
            body["draft_response_text"] = draft_response_text
        return self._request("POST", f"/v1/disputeos/cases/{case_id}/approve", json_body=body)

    def submit_case(
        self,
        case_id: str | UUID,
        *,
        draft_response_text: str | None = None,
    ) -> dict[str, Any]:
        body = {"draft_response_text": draft_response_text} if draft_response_text else {}
        return self._request("POST", f"/v1/disputeos/cases/{case_id}/submit", json_body=body)

    def resolve_case(
        self,
        case_id: str | UUID,
        *,
        draft_response_text: str | None = None,
        approver_id: str | None = None,
    ) -> dict[str, Any]:
        self.approve_case(case_id, approver_id=approver_id, draft_response_text=draft_response_text)
        return self.submit_case(case_id, draft_response_text=draft_response_text)

    # =========================================================================
    # Audit & Metrics
    # =========================================================================
    def get_overview_metrics(self) -> dict[str, Any]:
        return self._request("GET", "/v1/overview/metrics")

    def list_audit_events(
        self,
        *,
        correlation_id: str | UUID | None = None,
        payment_intent_id: str | UUID | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/audit-events",
            params={
                "correlation_id": str(correlation_id) if correlation_id else None,
                "payment_intent_id": str(payment_intent_id) if payment_intent_id else None,
                "event_type": event_type,
                "limit": limit,
                "offset": offset,
            },
        )

    def verify_chain(self, correlation_id: str | UUID) -> dict[str, Any]:
        res = self.list_audit_events(correlation_id=correlation_id)
        return {
            "verified": res.get("chain_verified"),
            "errors": res.get("chain_errors", []),
            "items": res.get("items", []),
        }

    verify_audit_chain = verify_chain

    def list_admin_audit_logs(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return self._request("GET", "/v1/orgs/audit-logs", params={"limit": limit, "offset": offset})

    # =========================================================================
    # System, Settings, Webhooks & DLQ
    # =========================================================================
    def list_service_accounts(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/orgs/service-accounts")

    def create_service_account(
        self,
        *,
        name: str,
        description: str = "",
        role: str = "AGENT_SERVICE",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/orgs/service-accounts",
            json_body={"name": name, "description": description, "role": role},
        )

    def list_api_keys(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/orgs/api-keys")

    def issue_api_key(
        self,
        *,
        name: str,
        service_account_id: str | UUID | None = None,
        role: str = "AGENT_SERVICE",
        scopes: list[str] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/orgs/api-keys",
            json_body={
                "name": name,
                "service_account_id": str(service_account_id) if service_account_id else None,
                "role": role,
                "scopes": scopes or [],
                "expires_at": expires_at,
            },
        )

    def rotate_api_key(self, key_id: str | UUID) -> dict[str, Any]:
        return self._request("POST", f"/v1/orgs/api-keys/{key_id}/rotate")

    def revoke_api_key(self, key_id: str | UUID) -> dict[str, Any]:
        return self._request("POST", f"/v1/orgs/api-keys/{key_id}/revoke")

    def list_webhook_endpoints(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/webhooks/endpoints")

    def create_webhook_endpoint(
        self,
        *,
        url: str,
        description: str = "",
        event_types: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/webhooks/endpoints",
            json_body={
                "url": url,
                "description": description,
                "event_types": event_types or ["*"],
            },
        )

    def disable_webhook_endpoint(self, endpoint_id: str | UUID) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/webhooks/endpoints/{endpoint_id}")

    def list_webhook_deliveries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/webhooks/deliveries", params={"limit": limit})

    def list_outbox_events(
        self,
        *,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/worker/outbox", params={"status_filter": status_filter, "limit": limit})

    def requeue_dead_letter(self, outbox_id: str | UUID) -> dict[str, Any]:
        return self._request("POST", f"/v1/worker/outbox/{outbox_id}/requeue")


class AsyncAegisClient:
    """Asynchronous typed client for AEGIS REST APIs (`/v1/*`)."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        bearer_token: str | None = None,
        organization_id: str | UUID | None = None,
        timeout: float | httpx.Timeout = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._bearer_token = bearer_token
        self._organization_id = str(organization_id) if organization_id else None
        self._max_retries = max(0, max_retries)
        self._backoff_factor = backoff_factor
        self._timeout = _build_timeout(timeout)
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout)
        self._owns_client = client is None

    async def __aenter__(self) -> AsyncAegisClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def set_token(self, bearer_token: str | None) -> None:
        self._bearer_token = bearer_token

    def set_api_key(self, api_key: str | None) -> None:
        self._api_key = api_key

    def set_organization_id(self, organization_id: str | UUID | None) -> None:
        self._organization_id = str(organization_id) if organization_id else None

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"X-Correlation-Id": str(uuid4())}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        elif self._api_key:
            headers["X-API-Key"] = self._api_key
        if self._organization_id:
            headers["X-Org-Id"] = self._organization_id
            headers["X-Tenant-Id"] = self._organization_id
        if extra:
            headers.update(extra)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
        headers: dict[str, str] | None = None,
        raw_bytes: bool = False,
    ) -> Any:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        req_headers = self._headers(headers)
        attempt = 0

        while True:
            try:
                resp = await self._client.request(
                    method,
                    path,
                    json=json_body,
                    data=data,
                    files=files,
                    params=clean_params,
                    headers=req_headers,
                )
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                    attempt += 1
                    await asyncio.sleep(self._backoff_factor * (2 ** (attempt - 1)))
                    continue

                if resp.status_code >= 400:
                    _handle_response_error(resp)

                if raw_bytes:
                    return resp.content
                if resp.status_code == 204 or not resp.content:
                    return None
                return resp.json()

            except httpx.TransportError as exc:
                if attempt < self._max_retries:
                    attempt += 1
                    await asyncio.sleep(self._backoff_factor * (2 ** (attempt - 1)))
                    continue
                raise exc

    # =========================================================================
    # Auth & Sessions
    # =========================================================================
    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        organization_name: str,
        organization_slug: str,
    ) -> dict[str, Any]:
        res = await self._request(
            "POST",
            "/v1/auth/register",
            json_body={
                "email": email,
                "password": password,
                "full_name": full_name,
                "organization_name": organization_name,
                "organization_slug": organization_slug,
            },
        )
        if isinstance(res, dict) and "access_token" in res:
            self.set_token(res["access_token"])
            if "active_tenant_id" in res:
                self.set_organization_id(res["active_tenant_id"])
        return res

    async def login(
        self,
        *,
        email: str,
        password: str,
        organization_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"email": email, "password": password}
        if organization_id is not None:
            body["organization_id"] = str(organization_id)
        res = await self._request("POST", "/v1/auth/login", json_body=body)
        if isinstance(res, dict) and "access_token" in res:
            self.set_token(res["access_token"])
            if "active_tenant_id" in res:
                self.set_organization_id(res["active_tenant_id"])
        return res

    async def me(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/auth/me")

    async def switch_org(self, organization_id: str | UUID) -> dict[str, Any]:
        self.set_organization_id(organization_id)
        return await self.me()

    async def list_orgs(self) -> list[dict[str, Any]]:
        info = await self.me()
        return info.get("organizations", [])

    async def create_org(self, *, name: str, slug: str) -> dict[str, Any]:
        return await self._request("POST", "/v1/orgs", json_body={"name": name, "slug": slug})

    async def update_current_org(self, *, name: str) -> dict[str, Any]:
        return await self._request("PATCH", "/v1/orgs/current", json_body={"name": name})

    async def list_members(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/orgs/members")

    async def invite_member(
        self,
        *,
        email: str,
        full_name: str = "Workspace Member",
        password: str | None = None,
        role: str = "OPERATOR",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"email": email, "full_name": full_name, "role": role}
        if password is not None:
            body["password"] = password
        return await self._request("POST", "/v1/orgs/members", json_body=body)

    async def update_member_role(self, user_id: str | UUID, *, role: str) -> dict[str, Any]:
        return await self._request("PATCH", f"/v1/orgs/members/{user_id}/role", json_body={"role": role})

    # =========================================================================
    # Guardian: Agents
    # =========================================================================
    async def create_agent(
        self,
        *,
        name: str,
        public_fingerprint: str,
        purpose: str = "autonomous-purchasing",
        framework: str = "langgraph",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/guardian/agents",
            json_body={
                "name": name,
                "public_fingerprint": public_fingerprint,
                "purpose": purpose,
                "framework": framework,
            },
        )

    async def list_agents(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/guardian/agents")

    async def get_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        str_id = str(agent_id)
        agents = await self.list_agents()
        for agent in agents:
            if str(agent.get("id")) == str_id:
                return agent
        raise AegisAPIError(404, f"Agent {agent_id} not found")

    async def update_agent_status(self, agent_id: str | UUID, status: str) -> dict[str, Any]:
        return await self._request("PATCH", f"/v1/guardian/agents/{agent_id}/status", json_body={"status": status})

    async def suspend_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        return await self.update_agent_status(agent_id, "SUSPENDED")

    async def revoke_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        return await self.update_agent_status(agent_id, "REVOKED")

    async def activate_agent(self, agent_id: str | UUID) -> dict[str, Any]:
        return await self.update_agent_status(agent_id, "ACTIVE")

    # =========================================================================
    # Guardian: Merchants
    # =========================================================================
    async def create_merchant(
        self,
        *,
        name: str,
        domain: str,
        category: str = "SOFTWARE",
        paypal_merchant_id: str | None = None,
        is_allowlisted: bool = True,
        is_sandbox_verified: bool = True,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/guardian/merchants",
            json_body={
                "name": name,
                "domain": domain,
                "category": category,
                "paypal_merchant_id": paypal_merchant_id,
                "is_allowlisted": is_allowlisted,
                "is_sandbox_verified": is_sandbox_verified,
            },
        )

    async def list_merchants(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/guardian/merchants")

    async def get_merchant(self, merchant_id: str | UUID) -> dict[str, Any]:
        str_id = str(merchant_id)
        merchants = await self.list_merchants()
        for m in merchants:
            if str(m.get("id")) == str_id:
                return m
        raise AegisAPIError(404, f"Merchant {merchant_id} not found")

    async def toggle_merchant_allowlist(self, merchant_id: str | UUID, is_allowlisted: bool) -> dict[str, Any]:
        return await self._request(
            "PATCH",
            f"/v1/guardian/merchants/{merchant_id}/allowlist",
            json_body={"is_allowlisted": is_allowlisted},
        )

    # =========================================================================
    # Guardian: Passports
    # =========================================================================
    async def create_passport(
        self,
        *,
        agent_id: str | UUID,
        total_budget_minor: int,
        per_tx_limit_minor: int,
        daily_limit_minor: int,
        human_approval_threshold_minor: int = 5000,
        allowed_merchant_ids: list[str | UUID] | None = None,
        allowed_categories: list[str] | None = None,
        allow_unknown_merchants: bool = False,
        currency: str = "USD",
        policy_version: str = "policy-v1",
        expires_in_days: int = 30,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/guardian/passports",
            json_body={
                "agent_id": str(agent_id),
                "total_budget_minor": total_budget_minor,
                "per_tx_limit_minor": per_tx_limit_minor,
                "daily_limit_minor": daily_limit_minor,
                "human_approval_threshold_minor": human_approval_threshold_minor,
                "allowed_merchant_ids": [str(m) for m in (allowed_merchant_ids or [])],
                "allowed_categories": allowed_categories or [],
                "allow_unknown_merchants": allow_unknown_merchants,
                "currency": currency.upper(),
                "policy_version": policy_version,
                "expires_in_days": expires_in_days,
            },
        )

    issue_passport = create_passport

    async def list_passports(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/guardian/passports")

    async def get_passport(self, passport_id: str | UUID) -> dict[str, Any]:
        str_id = str(passport_id)
        passports = await self.list_passports()
        for p in passports:
            if str(p.get("id")) == str_id:
                return p
        raise AegisAPIError(404, f"Passport {passport_id} not found")

    async def update_passport_policy(
        self,
        passport_id: str | UUID,
        *,
        per_tx_limit_minor: int | None = None,
        daily_limit_minor: int | None = None,
        human_approval_threshold_minor: int | None = None,
        allowed_merchant_ids: list[str | UUID] | None = None,
        allowed_categories: list[str] | None = None,
        allow_unknown_merchants: bool | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if per_tx_limit_minor is not None:
            body["per_tx_limit_minor"] = per_tx_limit_minor
        if daily_limit_minor is not None:
            body["daily_limit_minor"] = daily_limit_minor
        if human_approval_threshold_minor is not None:
            body["human_approval_threshold_minor"] = human_approval_threshold_minor
        if allowed_merchant_ids is not None:
            body["allowed_merchant_ids"] = [str(m) for m in allowed_merchant_ids]
        if allowed_categories is not None:
            body["allowed_categories"] = allowed_categories
        if allow_unknown_merchants is not None:
            body["allow_unknown_merchants"] = allow_unknown_merchants
        return await self._request("PATCH", f"/v1/guardian/passports/{passport_id}", json_body=body)

    async def revoke_passport(self, passport_id: str | UUID) -> dict[str, Any]:
        return await self._request("POST", f"/v1/guardian/passports/{passport_id}/revoke")

    # =========================================================================
    # Guardian: Proposals, Payments & Approvals
    # =========================================================================
    async def submit_purchase_proposal(
        self,
        *,
        agent_id: str | UUID,
        passport_id: str | UUID,
        merchant_id: str | UUID,
        merchant_name: str,
        merchant_category: str = "SOFTWARE",
        amount_minor: int,
        currency: str = "USD",
        item_summary: str = "",
        rationale: str = "",
        line_items: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
        quote_expires_in_seconds: int = 1800,
    ) -> dict[str, Any]:
        key = idempotency_key or f"sdk-{uuid4().hex[:16]}"
        return await self._request(
            "POST",
            "/v1/guardian/proposals",
            json_body={
                "agent_id": str(agent_id),
                "passport_id": str(passport_id),
                "merchant_id": str(merchant_id),
                "merchant_name": merchant_name,
                "merchant_category": merchant_category,
                "amount_minor": amount_minor,
                "currency": currency.upper(),
                "item_summary": item_summary,
                "line_items": line_items or [],
                "rationale": rationale,
                "idempotency_key": key,
                "quote_expires_in_seconds": quote_expires_in_seconds,
            },
        )

    asubmit_purchase_proposal = submit_purchase_proposal
    create_proposal = submit_purchase_proposal

    async def approve_proposal(
        self,
        intent_id: str | UUID,
        *,
        approver_id: str,
        comment: str | None = None,
        approved: bool = True,
        approval_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        params = {"approval_id": str(approval_id)} if approval_id else None
        return await self._request(
            "POST",
            f"/v1/guardian/proposals/{intent_id}/approve",
            params=params,
            json_body={"approver_id": approver_id, "approved": approved, "comment": comment},
        )

    async def reject_proposal(
        self,
        intent_id: str | UUID,
        *,
        approver_id: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        return await self.approve_proposal(intent_id, approver_id=approver_id, comment=comment, approved=False)

    decide_approval = approve_proposal

    async def initiate_checkout(
        self,
        intent_id: str | UUID,
        *,
        attempt_number: int = 1,
        idempotency_key: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/checkout",
            json_body={
                "attempt_number": attempt_number,
                "idempotency_key": idempotency_key,
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        )

    async def buyer_approved(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
        payer_id: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/buyer-approved",
            json_body={"attempt_id": str(attempt_id), "payer_id": payer_id},
        )

    async def capture_payment(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/capture",
            json_body={"attempt_id": str(attempt_id)},
        )

    capture = capture_payment

    async def buyer_declined(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/buyer-declined",
            json_body={"attempt_id": str(attempt_id), "reason": reason},
        )

    async def reconcile_payment(
        self,
        intent_id: str | UUID,
        *,
        attempt_id: str | UUID,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/guardian/payments/{intent_id}/reconcile",
            json_body={"attempt_id": str(attempt_id)},
        )

    async def get_payment(self, intent_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/guardian/payments/{intent_id}")

    async def get_payment_detail(self, intent_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/guardian/payments/{intent_id}/detail")

    async def list_payments(
        self,
        *,
        state: str | None = None,
        agent_id: str | UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/v1/guardian/payments",
            params={
                "state": state,
                "agent_id": str(agent_id) if agent_id else None,
                "limit": limit,
                "offset": offset,
            },
        )

    async def list_approvals(
        self,
        *,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/v1/guardian/approvals",
            params={"status_filter": status_filter, "limit": limit, "offset": offset},
        )

    async def get_approval(self, approval_id: str | UUID) -> dict[str, Any]:
        str_id = str(approval_id)
        approvals = await self.list_approvals()
        for apprv in approvals:
            if str(apprv.get("id")) == str_id:
                return apprv
        raise AegisAPIError(404, f"Approval {approval_id} not found")

    # =========================================================================
    # GhostPay: Timelines, Replay, Simulations, Agent DNA
    # =========================================================================
    async def get_replay_timeline(self, payment_intent_id: str | UUID) -> list[dict[str, Any]]:
        return await self._request("GET", f"/v1/ghostpay/timeline/by-payment/{payment_intent_id}")

    async def reconstruct_timeline(
        self,
        events: list[dict[str, Any]],
        evidence_records: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "POST",
            "/v1/ghostpay/timeline",
            json_body={"events": events, "evidence_records": evidence_records or []},
        )

    async def get_trace_timeline(self, trace_id: str | UUID) -> list[dict[str, Any]]:
        return await self._request("GET", f"/v1/ghostpay/traces/{trace_id}/timeline")

    async def create_investigation(
        self,
        trace_id: str | UUID,
        *,
        counterfactual_policies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/ghostpay/investigations",
            json_body={"trace_id": str(trace_id), "counterfactual_policies": counterfactual_policies or []},
        )

    async def list_investigations(
        self,
        *,
        payment_intent_id: str | UUID | None = None,
        consistency_status: str | None = None,
        drift_detected: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/ghostpay/investigations",
            params={
                "payment_intent_id": str(payment_intent_id) if payment_intent_id else None,
                "consistency_status": consistency_status,
                "drift_detected": drift_detected,
                "limit": limit,
                "offset": offset,
            },
        )

    async def get_investigation(self, investigation_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/ghostpay/investigations/{investigation_id}")

    async def get_investigation_evidence(self, investigation_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/ghostpay/investigations/{investigation_id}/evidence")

    async def replay_by_payment(
        self,
        intent_id: str | UUID,
        *,
        policy_version: str | None = None,
        persist_investigation: bool = True,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/ghostpay/replay/by-payment/{intent_id}",
            json_body={"policy_version": policy_version, "persist_investigation": persist_investigation},
        )

    async def simulate_by_payment(
        self,
        intent_id: str | UUID,
        *,
        overrides: dict[str, Any],
        policy_version: str | None = None,
        persist_investigation: bool = True,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/ghostpay/simulate/by-payment/{intent_id}",
            json_body={
                "overrides": overrides,
                "policy_version": policy_version,
                "persist_investigation": persist_investigation,
            },
        )

    async def run_counterfactual_simulation(
        self,
        replay_request: dict[str, Any],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/ghostpay/simulate",
            json_body={"request": replay_request, "overrides": overrides},
        )

    simulate = run_counterfactual_simulation

    async def compare_policies(
        self,
        replay_request: dict[str, Any],
        policies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/ghostpay/replay/compare",
            json_body={"replay_request": replay_request, "policies": policies},
        )

    async def get_agent_profile(self, agent_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/ghostpay/agents/{agent_id}/profile")

    get_profile = get_agent_profile

    async def analyze_agent_dna(
        self,
        agent_id: str | UUID,
        *,
        target_trace_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/ghostpay/agents/{agent_id}/analyze",
            json_body={"target_trace_id": str(target_trace_id) if target_trace_id else None},
        )

    async def ingest_trace(self, trace_payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/v1/ghostpay/traces/ingest", json_body=trace_payload)

    async def get_trace(self, trace_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/ghostpay/traces/{trace_id}")

    # =========================================================================
    # DisputeOS: Cases, Evidence & Reports
    # =========================================================================
    async def create_dispute_case(
        self,
        *,
        reason: str,
        buyer_claim: str,
        amount_minor: int,
        currency: str = "USD",
        source_type: str = "MANUAL",
        is_synthetic: bool = False,
        correlation_id: str | UUID | None = None,
        payment_intent_id: str | UUID | None = None,
        evidence_records: list[dict[str, Any]] | None = None,
        paypal_dispute_id: str | None = None,
        case_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "reason": reason,
            "buyer_claim": buyer_claim,
            "amount_minor": amount_minor,
            "currency": currency.upper(),
            "source_type": source_type,
            "is_synthetic": is_synthetic,
            "evidence_records": evidence_records or [],
            "paypal_dispute_id": paypal_dispute_id,
        }
        if correlation_id is not None:
            body["correlation_id"] = str(correlation_id)
        if payment_intent_id is not None:
            body["payment_intent_id"] = str(payment_intent_id)
        if case_id is not None:
            body["case_id"] = str(case_id)
        return await self._request("POST", "/v1/disputeos/cases", json_body=body)

    async def list_dispute_cases(
        self,
        *,
        status_filter: str | None = None,
        is_synthetic: bool | None = None,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/v1/disputeos/cases",
            params={"status_filter": status_filter, "is_synthetic": is_synthetic},
        )

    list_disputes = list_dispute_cases
    list_cases = list_dispute_cases

    async def get_dispute_case(self, case_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/disputeos/cases/{case_id}")

    async def seed_demo_case(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/disputeos/cases/seed-demo")

    async def assign_case(self, case_id: str | UUID, assigned_to: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/disputeos/cases/{case_id}/assign",
            json_body={"assigned_to": assigned_to},
        )

    async def add_case_note(self, case_id: str | UUID, body: str) -> dict[str, Any]:
        return await self._request("POST", f"/v1/disputeos/cases/{case_id}/notes", json_body={"body": body})

    async def attach_evidence(
        self,
        case_id: str | UUID,
        *,
        source_type: str,
        source_ref: str,
        title: str,
        content: Any,
        correlation_id: str | UUID | None = None,
        payment_intent_id: str | UUID | None = None,
        is_synthetic: bool = False,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/disputeos/cases/{case_id}/evidence",
            json_body={
                "source_type": source_type,
                "source_ref": source_ref,
                "title": title,
                "content": content,
                "correlation_id": str(correlation_id) if correlation_id else None,
                "payment_intent_id": str(payment_intent_id) if payment_intent_id else None,
                "is_synthetic": is_synthetic,
            },
        )

    async def upload_evidence_artifact(
        self,
        case_id: str | UUID,
        *,
        file_content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        title: str = "Uploaded Evidence Document",
        source_type: str = "DELIVERY_RECEIPT",
    ) -> dict[str, Any]:
        files = {"file": (filename, file_content, content_type)}
        data = {"title": title, "source_type": source_type}
        return await self._request("POST", f"/v1/disputeos/cases/{case_id}/artifacts", files=files, data=data)

    async def download_evidence_artifact(self, case_id: str | UUID, artifact_id: str | UUID) -> bytes:
        return await self._request(
            "GET",
            f"/v1/disputeos/cases/{case_id}/artifacts/{artifact_id}",
            raw_bytes=True,
        )

    async def run_case_analysis(self, case_id: str | UUID) -> dict[str, Any]:
        return await self._request("POST", f"/v1/disputeos/cases/{case_id}/analyze")

    run_analysis = run_case_analysis

    async def get_case_report(self, case_id: str | UUID) -> dict[str, Any]:
        return await self._request("GET", f"/v1/disputeos/cases/{case_id}/report")

    get_analysis = get_case_report
    generate_report = get_case_report

    async def approve_case(
        self,
        case_id: str | UUID,
        *,
        approver_id: str | None = None,
        draft_response_text: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if approver_id is not None:
            body["approver_id"] = approver_id
        if draft_response_text is not None:
            body["draft_response_text"] = draft_response_text
        return await self._request("POST", f"/v1/disputeos/cases/{case_id}/approve", json_body=body)

    async def submit_case(
        self,
        case_id: str | UUID,
        *,
        draft_response_text: str | None = None,
    ) -> dict[str, Any]:
        body = {"draft_response_text": draft_response_text} if draft_response_text else {}
        return await self._request("POST", f"/v1/disputeos/cases/{case_id}/submit", json_body=body)

    async def resolve_case(
        self,
        case_id: str | UUID,
        *,
        draft_response_text: str | None = None,
        approver_id: str | None = None,
    ) -> dict[str, Any]:
        await self.approve_case(case_id, approver_id=approver_id, draft_response_text=draft_response_text)
        return await self.submit_case(case_id, draft_response_text=draft_response_text)

    # =========================================================================
    # Audit & Metrics
    # =========================================================================
    async def get_overview_metrics(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/overview/metrics")

    async def list_audit_events(
        self,
        *,
        correlation_id: str | UUID | None = None,
        payment_intent_id: str | UUID | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/audit-events",
            params={
                "correlation_id": str(correlation_id) if correlation_id else None,
                "payment_intent_id": str(payment_intent_id) if payment_intent_id else None,
                "event_type": event_type,
                "limit": limit,
                "offset": offset,
            },
        )

    async def verify_chain(self, correlation_id: str | UUID) -> dict[str, Any]:
        res = await self.list_audit_events(correlation_id=correlation_id)
        return {
            "verified": res.get("chain_verified"),
            "errors": res.get("chain_errors", []),
            "items": res.get("items", []),
        }

    verify_audit_chain = verify_chain

    async def list_admin_audit_logs(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/v1/orgs/audit-logs", params={"limit": limit, "offset": offset})

    # =========================================================================
    # System, Settings, Webhooks & DLQ
    # =========================================================================
    async def list_service_accounts(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/orgs/service-accounts")

    async def create_service_account(
        self,
        *,
        name: str,
        description: str = "",
        role: str = "AGENT_SERVICE",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/orgs/service-accounts",
            json_body={"name": name, "description": description, "role": role},
        )

    async def list_api_keys(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/orgs/api-keys")

    async def issue_api_key(
        self,
        *,
        name: str,
        service_account_id: str | UUID | None = None,
        role: str = "AGENT_SERVICE",
        scopes: list[str] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/orgs/api-keys",
            json_body={
                "name": name,
                "service_account_id": str(service_account_id) if service_account_id else None,
                "role": role,
                "scopes": scopes or [],
                "expires_at": expires_at,
            },
        )

    async def rotate_api_key(self, key_id: str | UUID) -> dict[str, Any]:
        return await self._request("POST", f"/v1/orgs/api-keys/{key_id}/rotate")

    async def revoke_api_key(self, key_id: str | UUID) -> dict[str, Any]:
        return await self._request("POST", f"/v1/orgs/api-keys/{key_id}/revoke")

    async def list_webhook_endpoints(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/webhooks/endpoints")

    async def create_webhook_endpoint(
        self,
        *,
        url: str,
        description: str = "",
        event_types: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/webhooks/endpoints",
            json_body={
                "url": url,
                "description": description,
                "event_types": event_types or ["*"],
            },
        )

    async def disable_webhook_endpoint(self, endpoint_id: str | UUID) -> dict[str, Any]:
        return await self._request("DELETE", f"/v1/webhooks/endpoints/{endpoint_id}")

    async def list_webhook_deliveries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/webhooks/deliveries", params={"limit": limit})

    async def list_outbox_events(
        self,
        *,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/worker/outbox", params={"status_filter": status_filter, "limit": limit})

    async def requeue_dead_letter(self, outbox_id: str | UUID) -> dict[str, Any]:
        return await self._request("POST", f"/v1/worker/outbox/{outbox_id}/requeue")


class AgentAuthorizationTool:
    """Middleware helper for external LLM/LangGraph purchasing agents.

    Submits deterministic purchase authorization requests to AEGIS Guardian using
    an restricted API key and returns whether the spend is CHECKOUT_READY,
    AWAITING_APPROVAL, or DENIED — without ever granting raw payment credentials.
    """

    def __init__(self, client: AegisClient, *, agent_id: str | UUID, passport_id: str | UUID) -> None:
        self.client = client
        self.agent_id = str(agent_id)
        self.passport_id = str(passport_id)

    def request_purchase_authorization(
        self,
        *,
        merchant_id: str | UUID,
        merchant_name: str,
        merchant_category: str = "SOFTWARE",
        amount_minor: int,
        item_summary: str,
        rationale: str,
        currency: str = "USD",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.client.submit_purchase_proposal(
            agent_id=self.agent_id,
            passport_id=self.passport_id,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            merchant_category=merchant_category,
            amount_minor=amount_minor,
            currency=currency,
            item_summary=item_summary,
            rationale=rationale,
            idempotency_key=idempotency_key,
        )


class AsyncAgentAuthorizationTool:
    """Asynchronous middleware helper for external LLM purchasing agents."""

    def __init__(self, client: AsyncAegisClient, *, agent_id: str | UUID, passport_id: str | UUID) -> None:
        self.client = client
        self.agent_id = str(agent_id)
        self.passport_id = str(passport_id)

    async def request_purchase_authorization(
        self,
        *,
        merchant_id: str | UUID,
        merchant_name: str,
        merchant_category: str = "SOFTWARE",
        amount_minor: int,
        item_summary: str,
        rationale: str,
        currency: str = "USD",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await self.client.submit_purchase_proposal(
            agent_id=self.agent_id,
            passport_id=self.passport_id,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            merchant_category=merchant_category,
            amount_minor=amount_minor,
            currency=currency,
            item_summary=item_summary,
            rationale=rationale,
            idempotency_key=idempotency_key,
        )
