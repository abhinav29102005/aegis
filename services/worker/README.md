# Transactional Outbox & Reconciliation Worker (`services/worker/`)

**Branch:** `integration/nexus`
**Status:** Ready for team implementation.

## Responsibilities
- Poll `outbox_events` (`LedgerRepository.list_pending_outbox()`) and publish/process pending events.
- Reconcile `PENDING_PROVIDER` `PaymentAttempt`s against `PayPalSandboxClient.reconcile_order()`.

