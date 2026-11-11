import { describe, expect, it } from "vitest";
import { extractFastAPIError, AegisAPIError } from "../src/errors.js";

describe("GAP-015 FastAPI Error Extraction", () => {
  it("extracts simple string detail", () => {
    const payload = { detail: "Item not found" };
    const extracted = extractFastAPIError(payload, "Not Found", 404);
    expect(extracted.message).toBe("Item not found");
    expect(extracted.errorCode).toBeUndefined();
    expect(extracted.validationErrors).toBeUndefined();
  });

  it("extracts Pydantic validation error array [{ loc, msg, type }]", () => {
    const payload = {
      detail: [
        { loc: ["body", "amount_minor"], msg: "Input should be greater than 0", type: "greater_than" },
        { loc: ["body", "currency"], msg: "String should have at least 3 characters", type: "string_too_short" },
      ],
    };
    const extracted = extractFastAPIError(payload, "Unprocessable Entity", 422);
    expect(extracted.message).toContain("amount_minor: Input should be greater than 0");
    expect(extracted.message).toContain("currency: String should have at least 3 characters");
    expect(extracted.validationErrors?.length).toBe(2);
    expect(extracted.validationErrors?.[0].type).toBe("greater_than");
  });

  it("extracts detail.message and detail.error_code object structure", () => {
    const payload = {
      detail: {
        error_code: "AUTHENTICATION_FAILED",
        message: "Invalid or expired JWT token",
      },
    };
    const extracted = extractFastAPIError(payload, "Unauthorized", 401);
    expect(extracted.message).toBe("Invalid or expired JWT token");
    expect(extracted.errorCode).toBe("AUTHENTICATION_FAILED");
  });

  it("extracts top-level error_code and message", () => {
    const payload = {
      error_code: "PERMISSION_DENIED",
      message: "User lacks proposals:write permission",
      correlation_id: "corr-123",
    };
    const extracted = extractFastAPIError(payload, "Forbidden", 403);
    expect(extracted.message).toBe("User lacks proposals:write permission");
    expect(extracted.errorCode).toBe("PERMISSION_DENIED");
  });

  it("extracts top-level error and message (e.g. POLICY_DENIED)", () => {
    const payload = {
      error: "POLICY_DENIED",
      message: "Exceeds per-transaction spending limit of $50.00",
      reason_codes: ["DENIED_EXCEEDS_PER_TX_LIMIT"],
    };
    const extracted = extractFastAPIError(payload, "Forbidden", 403);
    expect(extracted.message).toBe("Exceeds per-transaction spending limit of $50.00");
  });

  it("handles non-object and raw string payloads gracefully", () => {
    const extracted1 = extractFastAPIError("<html>502 Bad Gateway</html>", "Bad Gateway", 502);
    expect(extracted1.message).toBe("<html>502 Bad Gateway</html>");

    const extracted2 = extractFastAPIError(null, "Internal Server Error", 500);
    expect(extracted2.message).toBe("Internal Server Error");

    const extracted3 = extractFastAPIError({}, "Service Unavailable", 503);
    expect(extracted3.message).toBe("Service Unavailable");
  });

  it("creates structured AegisAPIError with full metadata", () => {
    const payload = {
      detail: [{ loc: ["body", "passport_id"], msg: "Field required", type: "missing" }],
    };
    const extracted = extractFastAPIError(payload, "Unprocessable Entity", 422);
    const err = new AegisAPIError(422, extracted.message, payload, extracted.errorCode, extracted.validationErrors);

    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(AegisAPIError);
    expect(err.name).toBe("AegisAPIError");
    expect(err.statusCode).toBe(422);
    expect(err.message).toBe("AEGIS API HTTP 422: passport_id: Field required");
    expect(err.payload).toEqual(payload);
    expect(err.validationErrors?.length).toBe(1);
  });
});
