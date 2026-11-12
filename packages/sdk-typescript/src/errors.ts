/**
 * Error extraction and custom error classes for AEGIS SDK.
 * Handles FastAPI error responses, Pydantic validation errors, and domain errors.
 */

export interface PydanticValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  ctx?: Record<string, unknown>;
}

export interface ExtractedErrorInfo {
  message: string;
  errorCode?: string;
  validationErrors?: PydanticValidationError[];
}

/**
 * Robustly parses and extracts human-readable message and error details from FastAPI responses.
 * Handles:
 * - string detail: {"detail": "Not found"}
 * - array detail (Pydantic validation errors): {"detail": [{"loc": ["body", "amount"], "msg": "...", "type": "..."}]}
 * - object detail: {"detail": {"message": "Invalid token", "error_code": "AUTHENTICATION_FAILED"}}
 * - top-level error object: {"error_code": "PERMISSION_DENIED", "message": "Forbidden"}
 * - top-level error/msg: {"error": "POLICY_DENIED", "message": "Policy rejected"}
 * - raw string or unexpected shapes without throwing.
 */
export function extractFastAPIError(payload: unknown, statusText: string, statusCode: number): ExtractedErrorInfo {
  if (!payload || typeof payload !== "object") {
    const rawMsg = typeof payload === "string" && payload.trim() ? payload.trim() : (statusText || `HTTP ${statusCode}`);
    return { message: rawMsg };
  }

  const data = payload as Record<string, unknown>;
  let message = "";
  let errorCode: string | undefined = typeof data.error_code === "string" ? data.error_code : undefined;
  let validationErrors: PydanticValidationError[] | undefined;

  // 1. Check for FastAPI `detail` field
  if ("detail" in data) {
    const detail = data.detail;

    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      // Pydantic validation errors: [{ loc: [...], msg: "...", type: "..." }]
      validationErrors = detail.filter(
        (item): item is PydanticValidationError =>
          item !== null && typeof item === "object" && "msg" in item
      );

      if (validationErrors.length > 0) {
        message = validationErrors
          .map((err) => {
            const locStr = Array.isArray(err.loc) ? err.loc.filter((p) => p !== "body").join(".") : "";
            const prefix = locStr ? `${locStr}: ` : "";
            return `${prefix}${err.msg}`;
          })
          .join("; ");
      } else {
        message = "Validation error";
      }
    } else if (detail !== null && typeof detail === "object") {
      const detailObj = detail as Record<string, unknown>;
      if (typeof detailObj.message === "string") {
        message = detailObj.message;
      } else if (typeof detailObj.msg === "string") {
        message = detailObj.msg;
      } else if (typeof detailObj.error === "string") {
        message = detailObj.error;
      } else {
        message = JSON.stringify(detailObj);
      }

      if (!errorCode && typeof detailObj.error_code === "string") {
        errorCode = detailObj.error_code;
      }
    }
  }

  // 2. Fallbacks if detail was missing or empty
  if (!message) {
    if (typeof data.message === "string") {
      message = data.message;
    } else if (typeof data.msg === "string") {
      message = data.msg;
    } else if (typeof data.error === "string") {
      message = data.error;
    } else if (typeof data.error === "object" && data.error !== null) {
      const errObj = data.error as Record<string, unknown>;
      if (typeof errObj.message === "string") {
        message = errObj.message;
      } else {
        message = JSON.stringify(errObj);
      }
    } else {
      message = statusText || `Request failed with status ${statusCode}`;
    }
  }

  return { message, errorCode, validationErrors };
}

export class AegisAPIError extends Error {
  readonly statusCode: number;
  readonly payload: unknown;
  readonly errorCode?: string;
  readonly validationErrors?: PydanticValidationError[];

  constructor(statusCode: number, message: string, payload?: unknown, errorCode?: string, validationErrors?: PydanticValidationError[]) {
    super(`AEGIS API HTTP ${statusCode}: ${message}`);
    this.name = "AegisAPIError";
    this.statusCode = statusCode;
    this.payload = payload;
    this.errorCode = errorCode;
    this.validationErrors = validationErrors;

    // Restore prototype chain in environments compiling to older ES
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class AegisTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`AEGIS request timed out after ${timeoutMs}ms`);
    this.name = "AegisTimeoutError";
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class AegisPolicyViolationError extends Error {
  readonly outcome: string;
  readonly reasonCodes: string[];
  readonly violatedConstraints: string[];

  constructor(outcome: string, reasonCodes: string[], violatedConstraints: string[] = [], explanation?: string) {
    super(explanation || `AEGIS policy violation: outcome=${outcome}, reasons=${reasonCodes.join(", ")}`);
    this.name = "AegisPolicyViolationError";
    this.outcome = outcome;
    this.reasonCodes = reasonCodes;
    this.violatedConstraints = violatedConstraints;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class AegisApprovalRequiredError extends Error {
  readonly intentId: string;
  readonly explanation: string;

  constructor(intentId: string, explanation: string) {
    super(`AEGIS purchase intent ${intentId} requires human approval: ${explanation}`);
    this.name = "AegisApprovalRequiredError";
    this.intentId = intentId;
    this.explanation = explanation;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
