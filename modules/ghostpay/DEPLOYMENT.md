# GhostPay deployment and operations

## Service boundary

GhostPay is an authenticated, stateless, read-only forensic service. It replays
**initial authorization**, not later approval consumption or payment execution.
It uses Guardian's deterministic policy interface for `policy-v1`; request,
passport, and recorded decision versions must agree. An unsupported version
returns a client error. Save historical policy/passport snapshots: current ledger
balances cannot reconstruct past authorization inputs.

The included web console supports imported JSON, a labeled synthetic example,
replay, hypothetical limits/amounts/merchants, evidence findings, timelines, and
JSON result export. Tokens stay in page memory and are not persisted in browser
storage. Reloading clears the token.

## Build and start

Run commands from the repository root. Requires Docker Engine with Compose v2.
Generate private tenant credentials on the deployment host:

```sh
python - <<'PY'
import json, os, secrets
from pathlib import Path
# This tenant matches the bundled synthetic example. Use real tenant UUIDs for imports.
p = Path('.env.ghostpay')
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write("GHOSTPAY_TOKENS='" + json.dumps({secrets.token_urlsafe(48):
        '00000000-0000-4000-8000-000000000001'}) + "'\n")
PY
docker compose --env-file .env.ghostpay -f modules/ghostpay/deploy/compose.yaml up --build -d --wait
curl --fail http://127.0.0.1:8000/healthz
```

Use your secret manager to retrieve the generated token for the console; never
paste it into Git, screenshots, URLs, or shared logs. The process refuses to start
without a nonempty JSON token-to-tenant map and 32+ character ASCII tokens. For
multiple tenants, issue independent random tokens. Rotate by updating the private
configuration and recreating the service. Treat tokens as bearer credentials.

Compose binds only to loopback. Put an HTTPS reverse proxy in front of it for
remote access. Configure connection/header/body timeouts, a 2 MB request limit,
and per-client rate limits there. Restrict allowed origins at the proxy; the API
does not enable cross-origin browser access. Do not expose the container's port
directly to the internet without TLS. Uvicorn does not trust forwarded headers.
Host, DNS, TLS certificate issuance, and public deployment are operator-specific.

The runtime runs as UID 10001 with a read-only root filesystem, dropped Linux
capabilities, no-new-privileges, limited memory/CPU/processes, and a bounded tmpfs.
The image installs frozen dependencies without development tools and includes
packaged web assets. No PayPal or AI credentials are required or used.

For TLS-inspecting build environments, preserve the proxy and provide its CA:

```sh
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -f modules/ghostpay/deploy/Dockerfile -t ghostpay:local .
```

The optional CA exists only in the dependency-install build step, not the runtime.

## Routes and authentication

All forensic routes require `Authorization: Bearer <private-token>`. The token
selects the tenant; a caller-supplied `X-Tenant-Id` cannot change it in this app.
The public endpoints are the static console/assets and liveness checks. Automatic
OpenAPI/docs endpoints are disabled in the standalone service.

| Route | Behavior |
|---|---|
| `GET /healthz` | Liveness and read-only mode; not provider readiness |
| `GET /` | Static forensic console |
| `GET /v1/ghostpay/example` | Labeled synthetic ReplayRequest, only for demo tenant |
| `POST /v1/ghostpay/replay` | Analyze a complete submitted ReplayRequest |
| `POST /v1/ghostpay/simulate` | `{request, overrides}`; hypothetical initial authorization |
| `POST /v1/ghostpay/counterfactual` | Simulation alias |
| `POST /v1/ghostpay/timeline` | One transaction chain and associated evidence |
| `GET /v1/ghostpay/payments/{id}/replay` | Load a historical snapshot from configured read-only source |

Invalid credentials return 401; cross-tenant requests return 403. Invalid override
values/unsupported versions return 400, malformed request bodies 422, and bodies
above 2,097,152 bytes 413. Validation responses do not echo submitted content.
Stored-source errors return a generic 422; missing snapshots 404; missing source
configuration 503. Unexpected errors are server errors, never a success verdict.

Embedded router users must provide an authenticated tenant dependency using
`ghostpay.api.router._resolve_tenant_id` as the FastAPI dependency override key,
as `ghostpay.app.create_app` does. The bare module router retains its original
header-based integration contract and must not be exposed directly as an
authenticated public service.

## Historical snapshot source

For imported analysis, no database or volume is required. Requests/results are
not persisted; export any results you need to retain.

For identifier-based canonical replay, mount a trusted directory read-only at
`/snapshots` and set `GHOSTPAY_SNAPSHOT_DIR=/snapshots`. Files are:

```text
/snapshots/<tenant UUID>/<payment intent UUID>.json
```

Each file must contain the full historical `ReplayRequest`, including recorded
passport, quote, initial decision, events, and evidence. The loader validates
schema, size, tenant, and payment identity. It never falls back to current policy
or creates missing evidence. It rejects paths escaping the configured root.
Provision these snapshots through a trusted backend/operator process, not a
public upload endpoint. Preserve source records and provenance outside this
stateless service; grant UID 10001 read access to only the intended directory.

To integrate with a database-backed host, replace the directory adapter with a
read-only service returning the same historical contract. Do not query a mutable
passport and label it historical. No schema or ledger migrations are performed
by GhostPay.

## Meaning and limits of findings

- `CONSISTENT` means supplied records agree under the supported evaluator and
  local checks. It does not establish an authentic source or a real payment.
- `INTEGRITY_FAILURE` takes priority over incomplete evidence and decision drift.
- SHA-256 checks cover complete evidence content or its ingestion envelope.
  Legacy partial-content digests are rejected; migrate them only from trusted
  original content. Recomputing a digest for arbitrary supplied data does not
  authenticate it.
- Financial chains must start at sequence 1, be contiguous, and have valid hashes.
  Without an independently trusted terminal anchor, deleting an entire valid
  suffix cannot be proven from the submitted prefix alone.
- Identity bindings, duplicate IDs, correlations, and evidence ownership are
  checked. Wrong-payment evidence cannot satisfy completeness or support a
  timeline entry.
- Simulations intentionally vary policy/merchant/amount fields. Original source
  integrity/completeness failures remain failures after hypothetical changes.
- An approval record does not rewrite the original policy decision. Approval
  consumption and live financial authority remain Guardian responsibilities.
- This service does not attest to PayPal capture, perform recovery, or execute
  financial actions. Sandbox-backed acceptance remains NOT VERIFIED until the
  shared integration supplies and verifies that flow.

## Operations and acceptance

```sh
uv sync --python 3.12
uv run pytest -q
uv run ruff check packages modules/disputeos modules/ghostpay
git diff --check
docker compose --env-file .env.ghostpay -f modules/ghostpay/deploy/compose.yaml logs --tail=100
docker compose --env-file .env.ghostpay -f modules/ghostpay/deploy/compose.yaml down
```

The default pytest command uses isolated import mode to avoid test package name
collisions and includes Guardian, GhostPay, DisputeOS, and shared packages.
Guardian's separate lint findings are outside GhostPay's lint scope.

Before release: verify startup fails without credentials, valid/invalid/foreign
tenant requests, snapshot errors, replay and simulation, malformed/oversized
inputs, console behavior on desktop/mobile, and a no-payment-executed result.
Use the synthetic example: replay $39, set the limit to 3000 minor units, then
show the hypothetical denial and unchanged original. Tamper with an evidence
field without changing its hash to demonstrate integrity failure.

Tag the tested image/commit for release and retain the previous image for rollback.
Rebuild after dependency/security updates and rerun acceptance. Restarting this
stateless service cannot alter budgets or payments; it clears in-flight analysis
and browser tokens. Health checks establish liveness only. The private credential
map and externally managed snapshot archive need their own backup/access policy.


## Reproduce container and browser acceptance

The container harness generates temporary test credentials, starts a disposable
read-only container on loopback port 8765, and leaves its ID/token in the private
work directory for browser checks. These are test credentials, not production keys.
Use an unused port/service environment and remove the test container afterward.

```sh
docker build -f modules/ghostpay/deploy/Dockerfile -t ghostpay:review .
uv run python modules/ghostpay/tests/container_smoke.py
# Requires Playwright in the Node environment and an installed Chromium browser.
GHOSTPAY_TEST_TOKEN_FILE=/tmp/ghostpay-acceptance/token \
  GHOSTPAY_BROWSER_EXECUTABLE=/usr/bin/chromium \
  node modules/ghostpay/tests/browser.cjs
docker rm -f "$(cat /tmp/ghostpay-acceptance/container-id)"
```

If using Playwright's bundled Chromium, omit GHOSTPAY_BROWSER_EXECUTABLE. The
browser harness does not make live PayPal calls. The CI container job runs the
HTTP/runtime harness and always removes its own container.
