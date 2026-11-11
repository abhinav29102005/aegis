/**
 * Universal Webhook Signature Verification for AEGIS.
 * Supports BOTH Node.js (node:crypto) AND WebCrypto (globalThis.crypto.subtle)
 * for seamless operation across Node.js, Next.js Edge Middleware, Cloudflare Workers, and Deno/Bun.
 */

import { createHmac } from "node:crypto";

export interface ParsedAegisSignature {
  timestamp: number;
  signatures: string[];
}

export interface VerifyAegisSignatureOptions {
  rawBody: string | Uint8Array;
  signatureHeader: string;
  secret: string;
  toleranceSeconds?: number;
}

/**
 * Constant-time string equality check to prevent timing attacks.
 * Operates in pure JavaScript across all runtimes without requiring Buffer or node:crypto.
 */
export function timingSafeEqualString(a: string, b: string): boolean {
  if (typeof a !== "string" || typeof b !== "string") {
    return false;
  }
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

/**
 * Parses the canonical `AEGIS-Signature: t=<unix_seconds>,v1=<hex_hmac_sha256>` header.
 * Tolerates comma-separated items, variable spacing, and multiple v1 signatures.
 */
export function parseAegisSignatureHeader(header: string): ParsedAegisSignature | null {
  if (!header || typeof header !== "string") {
    return null;
  }

  let timestamp: number | null = null;
  const signatures: string[] = [];

  const parts = header.split(",");
  for (const part of parts) {
    const trimmed = part.trim();
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;

    const key = trimmed.slice(0, eqIdx).trim();
    const value = trimmed.slice(eqIdx + 1).trim();

    if (key === "t") {
      const parsed = parseInt(value, 10);
      if (!isNaN(parsed) && parsed > 0) {
        timestamp = parsed;
      }
    } else if (key === "v1" && value.length > 0) {
      signatures.push(value.toLowerCase());
    }
  }

  if (timestamp === null || signatures.length === 0) {
    return null;
  }

  return { timestamp, signatures };
}

function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const result = new Uint8Array(a.length + b.length);
  result.set(a, 0);
  result.set(b, a.length);
  return result;
}

function bufferToHex(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let hex = "";
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

/**
 * Compute HMAC-SHA256 signature using WebCrypto (crypto.subtle).
 */
async function computeHmacSha256WebCrypto(secret: string, data: Uint8Array): Promise<string> {
  const encoder = new TextEncoder();
  const keyBytes = encoder.encode(secret);

  const key = await globalThis.crypto.subtle.importKey(
    "raw",
    keyBytes as unknown as BufferSource,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const sigBuffer = await globalThis.crypto.subtle.sign("HMAC", key, data as unknown as BufferSource);
  return bufferToHex(sigBuffer);
}

/**
 * Compute HMAC-SHA256 signature using Node.js node:crypto (sync or fallback).
 */
function computeHmacSha256Node(secret: string, data: Uint8Array): string {
  return createHmac("sha256", secret).update(data).digest("hex");
}

/**
 * Encodes timestamp prefix and raw payload into Uint8Array for HMAC calculation.
 */
function prepareSignedData(timestamp: number, rawBody: string | Uint8Array): Uint8Array {
  const encoder = new TextEncoder();
  const prefixBytes = encoder.encode(`${timestamp}.`);

  if (typeof rawBody === "string") {
    return encoder.encode(`${timestamp}.${rawBody}`);
  } else {
    return concatBytes(prefixBytes, rawBody);
  }
}

/**
 * Canonical Universal Webhook Signature Verification (GAP-014).
 *
 * Verifies `AEGIS-Signature: t=<timestamp>,v1=<hex_hmac_sha256>` over `${t}.${rawBody}`.
 * Supports both Node.js and WebCrypto (Edge runtime, Cloudflare Workers, Next.js Middleware).
 *
 * @param rawBody - Raw webhook request body as UTF-8 string or Uint8Array.
 * @param signatureHeader - The `AEGIS-Signature` header value (e.g. `t=1700000000,v1=abc...`).
 * @param secret - Webhook signing secret (e.g. `whsec_...`).
 * @param toleranceSeconds - Maximum allowed clock skew in seconds (default 300 = 5 minutes). Set 0 to disable check.
 * @returns Promise<boolean> - True if signature matches and is within tolerance; false otherwise.
 */
export async function verifyAegisSignature(
  rawBody: string | Uint8Array,
  signatureHeader: string,
  secret: string,
  toleranceSeconds = 300
): Promise<boolean> {
  if (!rawBody || !signatureHeader || !secret) {
    return false;
  }

  const parsed = parseAegisSignatureHeader(signatureHeader);
  if (!parsed) {
    return false;
  }

  // Clock drift check
  if (toleranceSeconds > 0) {
    const nowSec = Math.floor(Date.now() / 1000);
    if (Math.abs(nowSec - parsed.timestamp) > toleranceSeconds) {
      return false;
    }
  }

  const signedBytes = prepareSignedData(parsed.timestamp, rawBody);

  let expectedHex: string;
  if (typeof globalThis.crypto?.subtle?.importKey === "function") {
    expectedHex = await computeHmacSha256WebCrypto(secret, signedBytes);
  } else {
    expectedHex = computeHmacSha256Node(secret, signedBytes);
  }

  // Constant-time comparison against any provided v1 signature
  return parsed.signatures.some((sig) => timingSafeEqualString(sig, expectedHex));
}

/**
 * Synchronous Webhook Signature Verification for Node.js environments.
 * Uses `node:crypto`.
 */
export function verifyAegisSignatureSync(
  rawBody: string | Uint8Array,
  signatureHeader: string,
  secret: string,
  toleranceSeconds = 300
): boolean {
  if (!rawBody || !signatureHeader || !secret) {
    return false;
  }

  const parsed = parseAegisSignatureHeader(signatureHeader);
  if (!parsed) {
    return false;
  }

  if (toleranceSeconds > 0) {
    const nowSec = Math.floor(Date.now() / 1000);
    if (Math.abs(nowSec - parsed.timestamp) > toleranceSeconds) {
      return false;
    }
  }

  const signedBytes = prepareSignedData(parsed.timestamp, rawBody);
  const expectedHex = computeHmacSha256Node(secret, signedBytes);

  return parsed.signatures.some((sig) => timingSafeEqualString(sig, expectedHex));
}

/**
 * Helper to compute an `AEGIS-Signature` header value (useful for tests or mocking).
 */
export async function createAegisSignatureHeader(
  rawBody: string | Uint8Array,
  secret: string,
  timestamp: number = Math.floor(Date.now() / 1000)
): Promise<string> {
  const signedBytes = prepareSignedData(timestamp, rawBody);
  let hex: string;
  if (typeof globalThis.crypto?.subtle?.importKey === "function") {
    hex = await computeHmacSha256WebCrypto(secret, signedBytes);
  } else {
    hex = computeHmacSha256Node(secret, signedBytes);
  }
  return `t=${timestamp},v1=${hex}`;
}

// ---------------------------------------------------------------------------
// Backward-compatible legacy functions
// ---------------------------------------------------------------------------

function canonicalSort(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalSort);
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = canonicalSort((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

/**
 * @deprecated Use verifyAegisSignature for canonical replay-protected webhook verification.
 */
export function verifyWebhookSignature(params: {
  payloadBody: Record<string, unknown>;
  signatureHeader: string;
  signingSecret: string;
}): boolean {
  const canonical = JSON.stringify(canonicalSort(params.payloadBody));
  const encoder = new TextEncoder();
  const canonicalBytes = encoder.encode(canonical);

  let expected: string;
  try {
    expected = computeHmacSha256Node(params.signingSecret, canonicalBytes);
  } catch {
    return false;
  }

  const provided = params.signatureHeader.replace(/^sha256=/, "").trim();
  return timingSafeEqualString(expected, provided);
}
