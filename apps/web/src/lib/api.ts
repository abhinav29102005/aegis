import { truncateId as formatTruncateId } from "./format";
import type {
  AgentRecord,
  DisputeCaseRecord,
  FinancialEventRecord,
  ListAgentsParams,
  ListAuditEventsParams,
  ListDisputesParams,
  ListMerchantsParams,
  ListPassportsParams,
  ListPaymentsParams,
  MerchantRecord,
  OverviewMetrics,
  PassportRecord,
  PaymentIntentRecord,
} from "./types";

export * from "./types";

// Runtime polyfill for global truncateId used across client pages
if (typeof globalThis !== "undefined") {
  (globalThis as unknown as { truncateId?: typeof formatTruncateId }).truncateId = formatTruncateId;
}

export class ApiClientError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
  }
}

export function getApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    return "";
  }
  return (
    process.env.API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");
}

export interface ApiRequestOptions {
  method?: string;
  token?: string | null;
  orgId?: string | null;
  body?: unknown;
  isFormData?: boolean;
  timeoutMs?: number;
  signal?: AbortSignal;
  params?: Record<string, string | number | boolean | null | undefined>;
}

export function buildQueryString(params?: Record<string, string | number | boolean | null | undefined>): string {
  if (!params) return "";
  const searchParams = new URLSearchParams();
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== null && val !== "") {
      searchParams.set(key, String(val));
    }
  }
  const qs = searchParams.toString();
  return qs ? `?${qs}` : "";
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? 15000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  if (options.signal) {
    if (options.signal.aborted) {
      controller.abort();
    } else {
      options.signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  let finalPath = path;
  if (options.params) {
    const qs = buildQueryString(options.params);
    if (qs) {
      finalPath = `${path}${path.includes("?") ? "&" : "?"}${qs.slice(1)}`;
    }
  }

  let targetUrl = finalPath;

  // In browser runtime, route /v1/ calls through the Next.js HttpOnly cookie BFF proxy
  if (typeof window !== "undefined") {
    if (finalPath.startsWith("/v1/")) {
      targetUrl = `/api/proxy/${finalPath.replace(/^\/v1\//, "")}`;
    }
  } else {
    // Server-side fetch needs full base URL
    if (finalPath.startsWith("/v1/") || finalPath.startsWith("/api/")) {
      targetUrl = `${getApiBaseUrl()}${finalPath}`;
    }
  }

  const headers: Record<string, string> = {};
  if (!options.isFormData) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }
  if (options.orgId) {
    headers["X-Org-Id"] = options.orgId;
  }

  try {
    const resp = await fetch(targetUrl, {
      method: options.method ?? "GET",
      headers,
      credentials: "same-origin",
      signal: controller.signal,
      body: options.isFormData
        ? (options.body as FormData)
        : options.body !== undefined
          ? JSON.stringify(options.body)
          : undefined,
    });

    const text = await resp.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (!resp.ok) {
      // Auto-evict and redirect cleanly to /login on 401 when in browser
      if (resp.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login?next=${next}`;
      }

      let msg = `HTTP ${resp.status}`;
      if (parsed && typeof parsed === "object") {
        const obj = parsed as Record<string, unknown>;
        if (typeof obj.message === "string") {
          msg = obj.message;
        } else if (typeof obj.detail === "string") {
          msg = obj.detail;
        } else if (Array.isArray(obj.detail)) {
          msg = obj.detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join(", ");
        } else if (obj.detail && typeof obj.detail === "object" && "message" in obj.detail) {
          msg = String((obj.detail as { message: unknown }).message);
        }
      }
      throw new ApiClientError(resp.status, msg, parsed);
    }
    return parsed as T;
  } catch (err) {
    if (controller.signal.aborted) {
      throw new ApiClientError(408, `Request timed out after ${timeoutMs}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// Strongly typed endpoint helper functions with pagination query params (limit, offset, q)
export async function getPayments(
  params?: ListPaymentsParams,
  options?: ApiRequestOptions,
): Promise<PaymentIntentRecord[]> {
  return apiRequest<PaymentIntentRecord[]>("/v1/guardian/payments", {
    ...options,
    params: {
      limit: params?.limit,
      offset: params?.offset,
      q: params?.q,
      state: params?.state,
      agent_id: params?.agent_id,
      merchant_id: params?.merchant_id,
      ...options?.params,
    },
  });
}

export async function getPayment(
  paymentId: string,
  options?: ApiRequestOptions,
): Promise<PaymentIntentRecord> {
  return apiRequest<PaymentIntentRecord>(`/v1/guardian/payments/${paymentId}`, options);
}

export async function getAgents(
  params?: ListAgentsParams,
  options?: ApiRequestOptions,
): Promise<AgentRecord[]> {
  return apiRequest<AgentRecord[]>("/v1/guardian/agents", {
    ...options,
    params: {
      limit: params?.limit,
      offset: params?.offset,
      q: params?.q,
      status: params?.status,
      ...options?.params,
    },
  });
}

export async function getMerchants(
  params?: ListMerchantsParams,
  options?: ApiRequestOptions,
): Promise<MerchantRecord[]> {
  return apiRequest<MerchantRecord[]>("/v1/guardian/merchants", {
    ...options,
    params: {
      limit: params?.limit,
      offset: params?.offset,
      q: params?.q,
      allowlisted: params?.allowlisted,
      ...options?.params,
    },
  });
}

export async function getPassports(
  params?: ListPassportsParams,
  options?: ApiRequestOptions,
): Promise<PassportRecord[]> {
  return apiRequest<PassportRecord[]>("/v1/guardian/passports", {
    ...options,
    params: {
      limit: params?.limit,
      offset: params?.offset,
      q: params?.q,
      status: params?.status,
      agent_id: params?.agent_id,
      ...options?.params,
    },
  });
}

export async function getDisputes(
  params?: ListDisputesParams,
  options?: ApiRequestOptions,
): Promise<DisputeCaseRecord[]> {
  return apiRequest<DisputeCaseRecord[]>("/v1/disputeos/cases", {
    ...options,
    params: {
      limit: params?.limit,
      offset: params?.offset,
      q: params?.q,
      status: params?.status,
      ...options?.params,
    },
  });
}

export async function getDispute(
  caseId: string,
  options?: ApiRequestOptions,
): Promise<DisputeCaseRecord> {
  return apiRequest<DisputeCaseRecord>(`/v1/disputeos/cases/${caseId}`, options);
}

export async function getAuditEvents(
  params?: ListAuditEventsParams,
  options?: ApiRequestOptions,
): Promise<FinancialEventRecord[]> {
  return apiRequest<FinancialEventRecord[]>("/v1/audit-events", {
    ...options,
    params: {
      limit: params?.limit,
      offset: params?.offset,
      q: params?.q,
      event_type: params?.event_type,
      actor_id: params?.actor_id,
      payment_intent_id: params?.payment_intent_id,
      ...options?.params,
    },
  });
}

export async function getOverviewMetrics(
  options?: ApiRequestOptions,
): Promise<OverviewMetrics> {
  return apiRequest<OverviewMetrics>("/v1/overview", options);
}
