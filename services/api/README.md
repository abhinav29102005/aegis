# Unified FastAPI Service (`services/api/`)

**Branch:** `integration/nexus`
**Status:** Ready for team implementation once `feature/guardian`, `feature/ghostpay`, and `feature/disputeos` are integrated.

## Planned Routes
- `/v1/guardian/...` — mounts `guardian.api.router`
- `/v1/ghostpay/...` — mounts `ghostpay.api.router`
- `/v1/disputeos/...` — mounts `disputeos.api.router` (already implemented in `modules/disputeos/`)
- `/v1/paypal/...` — PayPal webhook verification & reconciliation endpoints
- `/v1/audit-events` — tenant-scoped append-only `FinancialEvent` stream

