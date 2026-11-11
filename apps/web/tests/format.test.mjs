import test from "node:test";
import assert from "node:assert/strict";
import { badgeToneForStatus, formatMinorCurrency, truncateId } from "../src/lib/format.ts";

test("formatMinorCurrency formats USD minor units accurately", () => {
  assert.equal(formatMinorCurrency(12345, "USD"), "$123.45");
  assert.equal(formatMinorCurrency(0, "USD"), "$0.00");
});

test("truncateId shortens long UUIDs deterministically", () => {
  assert.equal(truncateId(null), "—");
  assert.equal(truncateId("short"), "short");
  assert.equal(truncateId("1234567890abcdef", 8), "12345678…");
});

test("badgeToneForStatus classifies terminal and drift states", () => {
  assert.equal(badgeToneForStatus("SUCCEEDED"), "success");
  assert.equal(badgeToneForStatus("AWAITING_APPROVAL"), "warning");
  assert.equal(badgeToneForStatus("DRIFT_DETECTED"), "danger");
  assert.equal(badgeToneForStatus("SYNTHETIC_DEMO"), "info");
});
