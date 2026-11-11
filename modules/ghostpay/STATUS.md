# GhostPay implementation status

## Implemented

- Typed counterfactual overrides, canonical model revalidation, JSON UUID/date
  normalization, controlled errors, and non-mutation guarantees.
- Guardian policy-v1 initial-authorization parity through its public deterministic
  interface; unknown/mismatched versions and impossible evaluation times rejected.
- Transaction/correlation/identity/financial/approval bindings; foreign evidence
  excluded from completeness and timeline references.
- Full-content/envelope evidence hashes; legacy partial digests rejected. Shared
  fixture hashes upgraded to cover their complete content without changing schemas.
- Contiguous event chains, duplicate-ID detection, deterministic references,
  missing-event reporting, and preservation of source failures in simulations.
- Authenticated stateless FastAPI application with tenant-bound bearer tokens,
  fail-closed configuration, bounded bodies, safe validation responses, security
  headers, and optional read-only historical snapshot source.
- Responsive read-only console: synthetic/imported records, replay, simulation,
  findings, timeline, export, and explicit source/payment-execution limitations.
- Frozen-dependency non-root container, read-only Compose runtime, resource limits,
  health check, deployment guide, and CI container build/fail-closed startup check.
- Default pytest discovery repaired; Makefile now includes Guardian and GhostPay.

## Verification evidence

- Full repository Python suite: 137 passed.
- GhostPay/shared package/DisputeOS lint: passed.
- Docker image: built successfully with trusted CA; no TLS checks disabled.
- Actual container: missing credentials block startup; configured service passes
  health, authenticated replay/simulation, invalid amount rejection, and non-root
  read-only runtime checks.
- Actual container + Chromium browser: 14 checks passed across desktop/mobile,
  authentication, synthetic replay, simulation, original preservation, export,
  tamper detection, stale-result clearing, reload/token clearing, and no page errors.
- Fixtures are synthetic; browser checks do not execute PayPal or AI calls.

## External acceptance still required

- Docker on the user's server is the selected target; that server has not yet
  been set up, so host installation, domain/TLS, and secrets are not configured. Local container verification is not public deployment.
- Live PayPal Sandbox acceptance is NOT VERIFIED and remains with the shared
  payment integration. GhostPay itself never creates/captures/reconciles payments.
- Production records need a trusted historical snapshot producer and retention/
  backup policy. Submitted JSON alone cannot authenticate its original source.
- Guardian's separate lint errors remain outside this module's lint ownership.

## Deliberate limits

The service analyzes initial decisions, not later approval consumption. Only the
current supported policy-v1 implementation is available; preserve released image/
source versions for historical reproducibility. No database migration or payment
mutation is performed. Detecting deletion of a valid chain suffix requires an
external trusted terminal anchor. See DEPLOYMENT.md for full operating limits.
