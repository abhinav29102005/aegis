import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  createAegisSignatureHeader,
  parseAegisSignatureHeader,
  timingSafeEqualString,
  verifyAegisSignature,
  verifyAegisSignatureSync,
  verifyWebhookSignature,
} from "../src/crypto.js";

describe("GAP-014 Universal Webhook Signature Verification", () => {
  const secret = "whsec_test_secret_key_123456789";
  const samplePayload = JSON.stringify({
    id: "evt-001",
    event_type: "PAYMENT_CAPTURED",
    amount_minor: 1500,
    currency: "USD",
  });

  it("parses valid canonical AEGIS-Signature headers", () => {
    const header = "t=1700000000,v1=abcdef0123456789";
    const parsed = parseAegisSignatureHeader(header);
    expect(parsed).toEqual({
      timestamp: 1700000000,
      signatures: ["abcdef0123456789"],
    });
  });

  it("tolerates extra whitespace and multiple v1 entries", () => {
    const header = "t=1700000000, v1=sig1, v1=sig2";
    const parsed = parseAegisSignatureHeader(header);
    expect(parsed?.timestamp).toBe(1700000000);
    expect(parsed?.signatures).toEqual(["sig1", "sig2"]);
  });

  it("returns null for malformed signature headers", () => {
    expect(parseAegisSignatureHeader("")).toBeNull();
    expect(parseAegisSignatureHeader("invalid-header")).toBeNull();
    expect(parseAegisSignatureHeader("t=abc,v1=sig")).toBeNull();
    expect(parseAegisSignatureHeader("t=1700000000")).toBeNull();
  });

  it("constant-time comparison correctly matches identical and mismatches non-identical strings", () => {
    expect(timingSafeEqualString("hello_world", "hello_world")).toBe(true);
    expect(timingSafeEqualString("hello_world", "hello_worlX")).toBe(false);
    expect(timingSafeEqualString("short", "longer_string")).toBe(false);
  });

  it("verifies signature with WebCrypto / default async verifier using string body", async () => {
    const now = Math.floor(Date.now() / 1000);
    const header = await createAegisSignatureHeader(samplePayload, secret, now);

    const valid = await verifyAegisSignature(samplePayload, header, secret, 300);
    expect(valid).toBe(true);
  });

  it("verifies signature using Uint8Array raw body", async () => {
    const now = Math.floor(Date.now() / 1000);
    const bodyBytes = new TextEncoder().encode(samplePayload);
    const header = await createAegisSignatureHeader(bodyBytes, secret, now);

    const valid = await verifyAegisSignature(bodyBytes, header, secret, 300);
    expect(valid).toBe(true);
  });

  it("synchronous Node.js verifier verifies valid signatures", () => {
    const now = Math.floor(Date.now() / 1000);
    const expectedHex = createHmac("sha256", secret).update(`${now}.${samplePayload}`).digest("hex");
    const header = `t=${now},v1=${expectedHex}`;

    const valid = verifyAegisSignatureSync(samplePayload, header, secret, 300);
    expect(valid).toBe(true);
  });

  it("rejects tampered raw body", async () => {
    const now = Math.floor(Date.now() / 1000);
    const header = await createAegisSignatureHeader(samplePayload, secret, now);

    const tampered = samplePayload.replace("1500", "9999");
    const valid = await verifyAegisSignature(tampered, header, secret, 300);
    expect(valid).toBe(false);
  });

  it("rejects wrong signing secret", async () => {
    const now = Math.floor(Date.now() / 1000);
    const header = await createAegisSignatureHeader(samplePayload, secret, now);

    const valid = await verifyAegisSignature(samplePayload, header, "wrong_secret", 300);
    expect(valid).toBe(false);
  });

  it("enforces clock drift tolerance (rejects timestamps older than tolerance)", async () => {
    const staleTime = Math.floor(Date.now() / 1000) - 305; // 305s ago (> 300s window)
    const header = await createAegisSignatureHeader(samplePayload, secret, staleTime);

    const valid = await verifyAegisSignature(samplePayload, header, secret, 300);
    expect(valid).toBe(false);

    // With larger tolerance window, it passes
    const validWithExtendedTolerance = await verifyAegisSignature(samplePayload, header, secret, 600);
    expect(validWithExtendedTolerance).toBe(true);
  });

  it("enforces clock drift tolerance for timestamps too far in future", async () => {
    const futureTime = Math.floor(Date.now() / 1000) + 350;
    const header = await createAegisSignatureHeader(samplePayload, secret, futureTime);

    const valid = await verifyAegisSignature(samplePayload, header, secret, 300);
    expect(valid).toBe(false);
  });

  it("supports backward-compatible legacy verifyWebhookSignature", () => {
    const body = { id: "evt-99", payload: { x: 10, y: 20 } };
    const canonical = JSON.stringify({ id: "evt-99", payload: { x: 10, y: 20 } });
    const digest = createHmac("sha256", secret).update(canonical).digest("hex");

    const valid = verifyWebhookSignature({
      payloadBody: body,
      signatureHeader: `sha256=${digest}`,
      signingSecret: secret,
    });
    expect(valid).toBe(true);

    const invalid = verifyWebhookSignature({
      payloadBody: body,
      signatureHeader: "sha256=invalidhex",
      signingSecret: secret,
    });
    expect(invalid).toBe(false);
  });
});
