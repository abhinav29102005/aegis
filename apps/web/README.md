# Unified Next.js Dashboard (`apps/web/`)

**Branch:** `integration/nexus`
**Status:** Ready for team implementation.

## Planned Routes
`/dashboard`, `/agents`, `/passports`, `/payments`, `/payments/[id]`, `/ghostpay`, `/ghostpay/replay/[id]`, `/disputes`, `/disputes/[id]`, `/audit`, `/settings`

## Contracts & Schemas
- Canonical JSON Schemas exported at `packages/contracts/schemas/contracts.schema.json`.
- Only use `NEXT_PUBLIC_*` env vars in browser code (`NEXT_PUBLIC_PAYPAL_CLIENT_ID`, `NEXT_PUBLIC_API_BASE_URL`). Never expose `PAYPAL_CLIENT_SECRET`.

