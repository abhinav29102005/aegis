import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";
import { AegisAPIError, AegisClient, verifyWebhookSignature } from "../dist/index.js";

test("AegisClient sends auth and org headers and parses responses", async () => {
  const calls = [];
  const mockFetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ total: 1, items: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const client = new AegisClient({
    baseUrl: "https://api.aegis.local/",
    apiKey: "aegis_test_key",
    organizationId: "11111111-1111-4111-8111-111111111111",
    fetchImpl: mockFetch,
  });

  const data = await client.listInvestigations({ limit: 10 });
  assert.equal(data.total, 1);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.aegis.local/v1/ghostpay/investigations?limit=10");
  assert.equal(calls[0].init.headers["X-API-Key"], "aegis_test_key");
  assert.equal(calls[0].init.headers["X-Org-Id"], "11111111-1111-4111-8111-111111111111");
});

test("AegisClient throws structured AegisAPIError on 4xx/5xx", async () => {
  const mockFetch = async () =>
    new Response(JSON.stringify({ error_code: "PERMISSION_DENIED", message: "Forbidden" }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });

  const client = new AegisClient({ baseUrl: "https://api.aegis.local", bearerToken: "jwt", fetchImpl: mockFetch });
  await assert.rejects(
    () => client.approveProposal("intent-1", "ops@example.com"),
    (err) => err instanceof AegisAPIError && err.statusCode === 403 && err.message.includes("Forbidden"),
  );
});

test("verifyWebhookSignature validates canonical HMAC-SHA256 payloads", () => {
  const secret = "whsec_ts_test";
  const body = { id: "evt-1", event_type: "PAYMENT_CAPTURED", payload: { b: 2, a: 1 } };
  const canonical = JSON.stringify({ event_type: "PAYMENT_CAPTURED", id: "evt-1", payload: { a: 1, b: 2 } });
  const digest = createHmac("sha256", secret).update(canonical, "utf8").digest("hex");

  assert.equal(
    verifyWebhookSignature({ payloadBody: body, signatureHeader: `sha256=${digest}`, signingSecret: secret }),
    true,
  );
  assert.equal(
    verifyWebhookSignature({ payloadBody: body, signatureHeader: "sha256=bad", signingSecret: secret }),
    false,
  );
});
