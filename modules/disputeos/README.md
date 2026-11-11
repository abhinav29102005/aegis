# DisputeOS (`modules/disputeos`)

**DisputeOS** is the grounded AI dispute intelligence, evidence graph, contradiction detection, and human-reviewed response drafting module for **AgentPay Nexus**.

---

## 1. Purpose

DisputeOS investigates payment and delivery disputes involving autonomous purchasing agents by:
- Managing multi-tenant dispute cases linked to canonical `PaymentIntent` and `correlation_id` records.
- Ingesting and normalizing transaction, fulfillment, carrier tracking, and customer support evidence with deterministic SHA-256 content hashes.
- Building a cross-referenced `EvidenceGraph` and detecting missing evidence and factual contradictions (e.g., carrier `DELIVERED` vs. merchant support `not delivered`).
- Generating grounded dispute summaries and draft responses where every factual claim cites a valid `evidence_id` and any unsupported/hallucinated claim is rejected and flagged.
- Working **deterministically without external AI credentials** (`LLM_PROVIDER=deterministic`), with safe fallback if an optional `LLMReviewerProtocol` implementation raises an error.
- Enforcing strict **human-in-the-loop approval** and **synthetic-case submission blocks** before any PayPal Sandbox Disputes API interaction.

---

## 2. Architecture

```text
modules/disputeos/
├── disputeos/
│   ├── cases/          # DisputeCaseService, approval & synthetic submission gates
│   ├── ingestion/      # DocumentIngestionService (normalizer & hashing)
│   ├── evidence/       # EvidenceGraph builder, missing-evidence & contradiction detectors
│   ├── analysis/       # CitationValidator, DisputeAnalyzer, deterministic + LLM reviewer
│   ├── reports/        # DisputeReport & generate_case_report
│   ├── paypal/         # PayPalDisputeAdapter (feature-flagged & approval-gated)
│   └── api/            # FastAPI APIRouter (/disputeos/*)
└── tests/
    ├── test_disputeos.py       # 10 mandatory domain & safety scenarios
    └── test_disputeos_api.py   # FastAPI TestClient endpoint & error-mapping tests
```

### Core Invariants
1. **Evidence Grounding**: Every factual claim in `DisputeAnalysis.citations` must reference an existing `evidence_id` on the case and a verifiable excerpt from that record. Unsupported claims are placed in `DisputeAnalysis.rejected_claims`.
2. **Missing & Contradictory Evidence**: Missing artifacts (e.g., `CARRIER_TRACKING`, `DELIVERY_RECEIPT`, `PAYPAL_CAPTURE`) populate `missing_evidence`; conflicting records populate `contradictions`.
3. **Deterministic Baseline & Safe AI Fallback**: `DisputeAnalyzer` produces full `DisputeAnalysis` results without API keys. If an injected `LLMReviewerProtocol` fails, the analyzer catches the failure, preserves case state, and falls back deterministically.
4. **Synthetic Labeling**: Synthetic demo cases are marked `is_synthetic=True` and `source_type=DisputeSourceType.SYNTHETIC_DEMO` and cannot be submitted externally (`SyntheticSubmissionError`).
5. **Human Approval Gate**: External submission requires `human_approved_for_submission=True` and a valid `approved_by` / `response_payload_hash` (`ApprovalGateError`).
6. **Tenant Isolation**: Every read/write operation validates `tenant_id` via `assert_same_tenant`, raising `TenantIsolationError` (mapped to HTTP `403`).

---

## 3. Installation

From the repository root using the workspace virtual environment (`uv` / `.venv`):

```bash
uv sync
```

To run module code or tests directly against the module path:

```bash
PYTHONPATH=modules/disputeos .venv/bin/pytest modules/disputeos/tests
```

---

## 4. Public Interfaces

### Domain & Service Layer
- `disputeos.cases.service`:
  - `DisputeCaseService`
  - `CaseNotFoundError`
  - `ApprovalGateError`
  - `SyntheticSubmissionError`
- `disputeos.ingestion.normalizer`:
  - `DocumentIngestionService`
- `disputeos.evidence.graph`:
  - `EvidenceGraph`
  - `build_evidence_graph`
- `disputeos.evidence.detector`:
  - `detect_missing_evidence`
  - `detect_contradictions`
- `disputeos.analysis.citations`:
  - `CandidateClaim`
  - `CitationValidator`
- `disputeos.analysis.analyzer`:
  - `DisputeAnalyzer`
  - `LLMReviewerProtocol`
- `disputeos.reports.generator`:
  - `DisputeReport`
  - `generate_case_report`
- `disputeos.paypal.adapter`:
  - `PayPalDisputeAdapter`

### FastAPI Router (`disputeos.api`)
- `create_disputeos_router(case_service=None, analyzer=None, ingestion_service=None, paypal_adapter=None) -> APIRouter`
- `router` (default `APIRouter(prefix="/disputeos", tags=["disputeos"])`)

#### Endpoints
All endpoints accept an `X-Tenant-Id` header (defaults to `DEFAULT_TENANT_UUID` when omitted).

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/disputeos/cases` | List dispute cases for the tenant |
| `POST` | `/disputeos/cases` | Create a new dispute case |
| `POST` | `/disputeos/cases/seed-demo` | Seed clearly labeled synthetic demo case from `build_synthetic_dispute_fixture()` |
| `GET` | `/disputeos/cases/{case_id}` | Fetch case, attached evidence, and latest analysis |
| `POST` | `/disputeos/cases/{case_id}/evidence` | Ingest and attach an evidence record to the case |
| `POST` | `/disputeos/cases/{case_id}/analyze` | Run `DisputeAnalyzer`, `build_evidence_graph`, and `generate_case_report` |
| `POST` | `/disputeos/cases/{case_id}/approve` | Record human approval (`approver_id`, `draft_response_text`) |
| `POST` | `/disputeos/cases/{case_id}/submit` | Guarded submission via `PayPalDisputeAdapter` |

#### HTTP Error Mapping
- `TenantIsolationError` -> `403 Forbidden`
- `ApprovalGateError` -> `403 Forbidden`
- `SyntheticSubmissionError` -> `403 Forbidden`
- `PayPalDisputesDisabledError` -> `403 Forbidden`
- `CaseNotFoundError` -> `404 Not Found`
- Invalid `X-Tenant-Id` header -> `400 Bad Request`

---

## 5. Dependencies

Workspace packages:
- `nexus-contracts` (`contracts`): `DisputeCase`, `DisputeAnalysis`, `DisputeEvidenceCitation`, `EvidenceRecord`, enums, hashing, and `build_synthetic_dispute_fixture`.
- `nexus-security` (`security`): `NexusSettings`, `DEFAULT_TENANT_UUID`, `TenantIsolationError`, `assert_same_tenant`.
- `nexus-paypal` (`paypal`): `PayPalSandboxClient`, `PayPalDisputesDisabledError`, `PayPalAPIError`.
- `nexus-database` (`database`): Optional persistence integration via `LedgerRepository`.

External runtime libraries (workspace `pyproject.toml`):
- `fastapi`
- `pydantic`
- `httpx`

---

## 6. Environment Variables

All configuration is loaded via `security.settings.NexusSettings` (no hardcoded secrets):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEFAULT_TENANT_ID` | `00000000-0000-4000-8000-000000000001` | Default tenant UUID when `X-Tenant-Id` is omitted |
| `LLM_PROVIDER` | `deterministic` | AI mode (`deterministic` requires no external credentials) |
| `OPENAI_API_KEY` | `""` | Optional OpenAI credential when LLM reviewer is enabled |
| `GOOGLE_API_KEY` | `""` | Optional Google AI credential when LLM reviewer is enabled |
| `PAYPAL_MODE` | `sandbox` | Must remain `sandbox` |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` | PayPal Sandbox API base URL |
| `PAYPAL_CLIENT_ID` | `""` | PayPal Sandbox OAuth client ID |
| `PAYPAL_CLIENT_SECRET` | `""` | PayPal Sandbox OAuth client secret |
| `PAYPAL_DISPUTES_API_ENABLED` | `false` | Feature flag gating external PayPal Disputes API calls |

---

## 7. Tests

Run the DisputeOS test suite from the worktree root:

```bash
PYTHONPATH=modules/disputeos /home/bigboyaks/Projects/agentpay-nexus/.venv/bin/pytest modules/disputeos/tests -v
```

### Mandatory Scenarios (`tests/test_disputeos.py`)
1. Valid `evidence_id` citations match existing case evidence.
2. Missing evidence (`CARRIER_TRACKING`, `DELIVERY_RECEIPT`, `PAYPAL_CAPTURE`) is detected and reported.
3. Contradictory delivery claims (carrier `DELIVERED` vs. support message `not delivered`) are flagged in `contradictions`.
4. Dispute summaries are grounded in available case evidence.
5. Unsupported/hallucinated claims from an `LLMReviewerProtocol` are rejected and listed in `rejected_claims`.
6. Cross-tenant access raises `TenantIsolationError` (and HTTP `403` in the API).
7. Human approval is enforced before any external submission.
8. Synthetic demo cases are labeled (`is_synthetic=True`, `source_type=SYNTHETIC_DEMO`) and blocked from external submission.
9. Case reports and analyses are generated deterministically without external AI credentials.
10. Exceptions raised by an injected `LLMReviewerProtocol` do not corrupt case state and safely fall back to deterministic analysis.

### API Integration Tests (`tests/test_disputeos_api.py`)
Tests all `/disputeos/*` FastAPI endpoints using `fastapi.testclient.TestClient`, including seeding, analysis, approval, guarded submission, and HTTP `400`/`403`/`404` mapping.

---

## 8. Integration Contracts

DisputeOS consumes and produces canonical `contracts.models` objects:
- **Inputs**: `DisputeCase`, `EvidenceRecord`, `PaymentIntent`, `QuoteSnapshot`, `AuthorizationDecision`, `ApprovalRecord`.
- **Outputs**: `DisputeAnalysis` (with `DisputeEvidenceCitation`, `DisputeRecommendation`), `DisputeCase` status updates (`DisputeStatus`), `DisputeReport`, and `EvidenceGraph`.
- **Unified API Mount**: `services/api` mounts `disputeos.api.router` under `/v1` (`/v1/disputeos/*`).

---

## 9. Security Considerations

- **No Autonomous External Submission**: Neither an LLM reviewer nor automated analysis can submit a dispute response to PayPal; explicit human approval (`approve`) and `PAYPAL_DISPUTES_API_ENABLED=true` are mandatory.
- **Synthetic Data Containment**: Synthetic demo fixtures cannot leak into external PayPal Sandbox dispute submissions.
- **Multi-Tenant Fail-Closed Isolation**: Every case, evidence, and analysis lookup checks `tenant_id` via `assert_same_tenant`.
- **Tamper-Evident Hashing**: Evidence payloads and approved response drafts are bound via canonical SHA-256 hashes (`compute_payload_hash`).
- **No Hardcoded Secrets**: API keys and PayPal credentials are read strictly from environment variables.

---

## 10. Limitations

- Default in-memory service storage in standalone module usage is ephemeral unless backed by `packages/database` `LedgerRepository`.
- PayPal Customer Disputes API v1 integration is sandbox-only and feature-flagged off by default (`PAYPAL_DISPUTES_API_ENABLED=false`); live submission paths without sandbox Dispute API permissions are intentionally blocked.
- Contradiction detection in deterministic mode relies on structured evidence fields (`status`, `message`, delivery indicators) rather than arbitrary unstructured OCR/PDF parsing.

---

## 11. Implementation Checklist

- [x] Canonical `DisputeCase`, `DisputeAnalysis`, `EvidenceRecord`, and `DisputeEvidenceCitation` integration
- [x] Tenant-isolated `DisputeCaseService` with approval and synthetic submission gates
- [x] Evidence ingestion, normalization, graph construction, and missing/contradiction detection
- [x] Grounded `CitationValidator` and deterministic-first `DisputeAnalyzer` with safe LLM fallback
- [x] Deterministic `DisputeReport` generation without external AI credentials
- [x] Feature-flagged `PayPalDisputeAdapter`
- [x] FastAPI router (`disputeos.api.router`) with full HTTP status mapping
- [x] 10 mandatory domain test scenarios + FastAPI `TestClient` suite
