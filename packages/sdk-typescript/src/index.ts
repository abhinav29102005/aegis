import { createHmac, timingSafeEqual } from "node:crypto";

export class AegisAPIError extends Error {
  readonly statusCode: number;
  readonly payload: unknown;

  constructor(statusCode: number, message: string, payload?: unknown) {
    super(`AEGIS API HTTP ${statusCode}: ${message}`);
    this.name = "AegisAPIError";
    this.statusCode = statusCode;
    this.payload = payload;
  }
}

export interface AegisClientOptions {
  baseUrl?: string;
  apiKey?: string;
  bearerToken?: string;
  organizationId?: string;
  fetchImpl?: typeof fetch;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  role: string;
  created_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  full_name: string;
  active_tenant_id: string;
  active_role: string;
  permissions: string[];
  organizations: OrganizationSummary[];
}

export interface SubmitProposalInput {
  agent_id: string;
  passport_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_category?: string;
  amount_minor: number;
  currency?: string;
  item_summary: string;
  rationale: string;
  line_items?: Array<Record<string, unknown>>;
  idempotency_key?: string;
}

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

export function verifyWebhookSignature(params: {
  payloadBody: Record<string, unknown>;
  signatureHeader: string;
  signingSecret: string;
}): boolean {
  const canonical = JSON.stringify(canonicalSort(params.payloadBody));
  const expected = createHmac("sha256", params.signingSecret).update(canonical, "utf8").digest("hex");
  const provided = params.signatureHeader.replace(/^sha256=/, "").trim();
  if (expected.length !== provided.length) {
    return false;
  }
  return timingSafeEqual(Buffer.from(expected, "utf8"), Buffer.from(provided, "utf8"));
}

export class AegisClient {
  private readonly baseUrl: string;
  private apiKey?: string;
  private bearerToken?: string;
  private organizationId?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AegisClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.bearerToken = options.bearerToken;
    this.organizationId = options.organizationId;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  setToken(token?: string): void {
    this.bearerToken = token;
  }

  setApiKey(apiKey?: string): void {
    this.apiKey = apiKey;
  }

  setOrganizationId(orgId?: string): void {
    this.organizationId = orgId;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    query?: Record<string, string | number | boolean | undefined>,
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined) {
          url.searchParams.set(k, String(v));
        }
      }
    }

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.bearerToken) {
      headers.Authorization = `Bearer ${this.bearerToken}`;
    } else if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    }
    if (this.organizationId) {
      headers["X-Org-Id"] = this.organizationId;
    }

    const resp = await this.fetchImpl(url.toString(), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
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
      const msg =
        parsed && typeof parsed === "object" && "message" in parsed
          ? String((parsed as { message: unknown }).message)
          : resp.statusText;
      throw new AegisAPIError(resp.status, msg, parsed);
    }
    return parsed as T;
  }

  register(input: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
    organization_slug: string;
  }): Promise<AuthTokenResponse> {
    return this.request<AuthTokenResponse>("POST", "/v1/auth/register", input);
  }

  login(input: { email: string; password: string; organization_id?: string }): Promise<AuthTokenResponse> {
    return this.request<AuthTokenResponse>("POST", "/v1/auth/login", input);
  }

  getOverviewMetrics(): Promise<Record<string, unknown>> {
    return this.request("GET", "/v1/overview/metrics");
  }

  listAgents(): Promise<Array<Record<string, unknown>>> {
    return this.request("GET", "/v1/guardian/agents");
  }

  createAgent(input: {
    name: string;
    purpose?: string;
    framework?: string;
    public_fingerprint: string;
  }): Promise<Record<string, unknown>> {
    return this.request("POST", "/v1/guardian/agents", input);
  }

  listMerchants(): Promise<Array<Record<string, unknown>>> {
    return this.request("GET", "/v1/guardian/merchants");
  }

  createMerchant(input: {
    name: string;
    domain: string;
    category?: string;
    is_allowlisted?: boolean;
  }): Promise<Record<string, unknown>> {
    return this.request("POST", "/v1/guardian/merchants", input);
  }

  listPassports(): Promise<Array<Record<string, unknown>>> {
    return this.request("GET", "/v1/guardian/passports");
  }

  createPassport(input: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", "/v1/guardian/passports", input);
  }

  submitPurchaseProposal(input: SubmitProposalInput): Promise<Record<string, unknown>> {
    return this.request("POST", "/v1/guardian/proposals", {
      ...input,
      merchant_category: input.merchant_category ?? "SOFTWARE",
      currency: (input.currency ?? "USD").toUpperCase(),
      line_items: input.line_items ?? [],
      idempotency_key: input.idempotency_key ?? `tssdk-${crypto.randomUUID()}`,
    });
  }

  listPayments(params?: { state?: string; limit?: number; offset?: number }): Promise<Array<Record<string, unknown>>> {
    return this.request("GET", "/v1/guardian/payments", undefined, params);
  }

  getPaymentDetail(intentId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/v1/guardian/payments/${intentId}/detail`);
  }

  approveProposal(intentId: string, approverId: string, comment?: string): Promise<Record<string, unknown>> {
    return this.request("POST", `/v1/guardian/proposals/${intentId}/approve`, {
      approver_id: approverId,
      approved: true,
      comment,
    });
  }

  initiateCheckout(intentId: string): Promise<Record<string, unknown>> {
    return this.request("POST", `/v1/guardian/payments/${intentId}/checkout`, { attempt_number: 1 });
  }

  replayByPayment(intentId: string): Promise<Record<string, unknown>> {
    return this.request("POST", `/v1/ghostpay/replay/by-payment/${intentId}`, {});
  }

  simulateByPayment(
    intentId: string,
    overrides: Record<string, unknown>,
    persistInvestigation = true,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", `/v1/ghostpay/simulate/by-payment/${intentId}`, {
      overrides,
      persist_investigation: persistInvestigation,
    });
  }

  listInvestigations(params?: {
    payment_intent_id?: string;
    limit?: number;
  }): Promise<Record<string, unknown>> {
    return this.request("GET", "/v1/ghostpay/investigations", undefined, params);
  }

  listDisputes(): Promise<Array<Record<string, unknown>>> {
    return this.request("GET", "/v1/disputeos/cases");
  }

  getDispute(caseId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/v1/disputeos/cases/${caseId}`);
  }

  listAuditEvents(params?: {
    correlation_id?: string;
    payment_intent_id?: string;
    limit?: number;
  }): Promise<Record<string, unknown>> {
    return this.request("GET", "/v1/audit-events", undefined, params);
  }
}
