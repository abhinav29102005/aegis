/**
 * Unified AegisClient for AgentPay Nexus.
 * Provides typed access to Guardian, GhostPay, DisputeOS, Webhooks, and Platform APIs
 * with automatic retries, configurable timeouts, error parsing, and pagination iterators.
 */

import { extractFastAPIError, AegisAPIError, AegisTimeoutError } from "./errors.js";
import type {
  AgentBehaviorProfile,
  AgentDNAAnomalyResult,
  AgentIdentity,
  ApiKeySummary,
  ApprovalActionResponse,
  ApprovalRecord,
  ApprovalStatus,
  AttachEvidenceInput,
  AttachEvidenceResponse,
  AuthTokenResponse,
  CheckoutResponse,
  CreateAgentInput,
  CreateDisputeCaseInput,
  CreateMerchantInput,
  CreatePassportInput,
  CreateWebhookEndpointInput,
  DisputeCase,
  DisputeCaseDetailResponse,
  DisputeOSEvidenceBundle,
  DisputeReport,
  HumanApprovalOptions,
  InvestigationListResponse,
  InvestigationReport,
  Merchant,
  OrgAuditLog,
  OrganizationSummary,
  OrgMemberSummary,
  OutboxEvent,
  OverviewMetrics,
  PassportStatus,
  PaymentAttempt,
  PaymentDetailResponse,
  PaymentIntent,
  PaymentState,
  PaymentTrace,
  PolicyComparisonReport,
  ProposalSubmissionResponse,
  ReplayRequest,
  ReplayResult,
  ReplayTimelineEntry,
  Role,
  ServiceAccountSummary,
  SpendingPassport,
  SubmitDisputeResponse,
  SubmitProposalInput,
  UpdatePassportInput,
  UserMeResponse,
  WebhookDelivery,
  WebhookEndpoint,
} from "./types.js";

export interface AegisClientOptions {
  baseUrl?: string;
  apiKey?: string;
  bearerToken?: string;
  organizationId?: string;
  timeoutMs?: number;
  maxRetries?: number;
  retryDelayMs?: number;
  fetchImpl?: typeof fetch;
}

export interface RequestOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
  maxRetries?: number;
  headers?: Record<string, string>;
  query?: Record<string, string | number | boolean | undefined>;
}

export interface PaginationOptions {
  pageSize?: number;
  maxItems?: number;
}

const TRANSIENT_STATUS_CODES = new Set([500, 502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class AegisClient {
  private readonly baseUrl: string;
  private apiKey?: string;
  private bearerToken?: string;
  private organizationId?: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly retryDelayMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AegisClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.bearerToken = options.bearerToken;
    this.organizationId = options.organizationId;
    this.timeoutMs = options.timeoutMs ?? 15000;
    this.maxRetries = options.maxRetries ?? 2;
    this.retryDelayMs = options.retryDelayMs ?? 150;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
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

  // ---------------------------------------------------------------------------
  // Core HTTP Engine (Timeouts, Retries, Error Extraction)
  // ---------------------------------------------------------------------------

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options: RequestOptions = {}
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (options.query) {
      for (const [k, v] of Object.entries(options.query)) {
        if (v !== undefined) {
          url.searchParams.set(k, String(v));
        }
      }
    }

    const headers: Record<string, string> = {
      Accept: "application/json",
      "X-Correlation-Id": crypto.randomUUID(),
      ...options.headers,
    };

    if (body !== undefined && !(body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    if (this.bearerToken) {
      headers.Authorization = `Bearer ${this.bearerToken}`;
    } else if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    }

    if (this.organizationId) {
      headers["X-Org-Id"] = this.organizationId;
    }

    const serializedBody =
      body === undefined
        ? undefined
        : body instanceof FormData
        ? body
        : typeof body === "string"
        ? body
        : JSON.stringify(body);

    const timeoutLimit = options.timeoutMs ?? this.timeoutMs;
    const maxRetries = options.maxRetries ?? this.maxRetries;

    let attempt = 0;
    while (true) {
      const controller = new AbortController();
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, timeoutLimit);

      let signal: AbortSignal = controller.signal;
      if (options.signal) {
        if (options.signal.aborted) {
          clearTimeout(timer);
          throw new DOMException("Aborted", "AbortError");
        }
        options.signal.addEventListener("abort", () => controller.abort(), { once: true });
      }

      try {
        const resp = await this.fetchImpl(url.toString(), {
          method,
          headers,
          body: serializedBody,
          signal,
        });
        clearTimeout(timer);

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
          // Check if retryable transient error
          if (TRANSIENT_STATUS_CODES.has(resp.status) && attempt < maxRetries) {
            attempt++;
            const backoff = this.retryDelayMs * Math.pow(2, attempt - 1) + Math.random() * 50;
            await sleep(backoff);
            continue;
          }

          const extracted = extractFastAPIError(parsed, resp.statusText, resp.status);
          throw new AegisAPIError(
            resp.status,
            extracted.message,
            parsed,
            extracted.errorCode,
            extracted.validationErrors
          );
        }

        return parsed as T;
      } catch (err) {
        clearTimeout(timer);
        if (timedOut) {
          throw new AegisTimeoutError(timeoutLimit);
        }

        // Retry on network errors
        if (
          attempt < maxRetries &&
          !(err instanceof AegisAPIError) &&
          !(err instanceof DOMException && err.name === "AbortError" && !timedOut)
        ) {
          attempt++;
          const backoff = this.retryDelayMs * Math.pow(2, attempt - 1) + Math.random() * 50;
          await sleep(backoff);
          continue;
        }

        throw err;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Pagination Helpers
  // ---------------------------------------------------------------------------

  async *paginate<T>(
    fetcher: (params: { limit: number; offset: number }) => Promise<T[] | { items: T[]; total?: number }>,
    options: PaginationOptions = {}
  ): AsyncIterableIterator<T> {
    const pageSize = options.pageSize ?? 50;
    const maxItems = options.maxItems ?? Number.POSITIVE_INFINITY;
    let offset = 0;
    let yielded = 0;

    while (yielded < maxItems) {
      const res = await fetcher({ limit: pageSize, offset });
      const items = Array.isArray(res) ? res : res.items;

      if (!items || items.length === 0) {
        break;
      }

      for (const item of items) {
        yield item;
        yielded++;
        if (yielded >= maxItems) break;
      }

      if (items.length < pageSize) {
        break;
      }

      offset += items.length;
    }
  }

  // ---------------------------------------------------------------------------
  // Platform & Health
  // ---------------------------------------------------------------------------

  health(): Promise<{ status: string; service: string; env?: string }> {
    return this.request("GET", "/health");
  }

  readiness(): Promise<{ status: string; database: string; paypal_configured: boolean }> {
    return this.request("GET", "/ready");
  }

  getOverviewMetrics(): Promise<OverviewMetrics> {
    return this.request("GET", "/v1/overview/metrics");
  }

  listAuditEvents(params?: {
    correlation_id?: string;
    payment_intent_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ total: number; events: Array<Record<string, unknown>> }> {
    return this.request("GET", "/v1/audit-events", undefined, { query: params });
  }

  listAuditEventsIterator(params?: {
    correlation_id?: string;
    payment_intent_id?: string;
    maxItems?: number;
  }): AsyncIterableIterator<Record<string, unknown>> {
    return this.paginate(
      async ({ limit, offset }) => {
        const res = await this.listAuditEvents({ ...params, limit, offset });
        return { items: res.events, total: res.total };
      },
      { maxItems: params?.maxItems }
    );
  }

  // ---------------------------------------------------------------------------
  // Auth & Organization Management
  // ---------------------------------------------------------------------------

  register(input: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
    organization_slug: string;
  }): Promise<AuthTokenResponse> {
    return this.request("POST", "/v1/auth/register", input);
  }

  login(input: {
    email: string;
    password: string;
    organization_id?: string;
  }): Promise<AuthTokenResponse> {
    return this.request("POST", "/v1/auth/login", input);
  }

  getMe(): Promise<UserMeResponse> {
    return this.request("GET", "/v1/auth/me");
  }

  createOrganization(input: { name: string; slug: string }): Promise<OrganizationSummary> {
    return this.request("POST", "/v1/orgs", input);
  }

  updateCurrentOrganization(input: { name?: string }): Promise<OrganizationSummary> {
    return this.request("PATCH", "/v1/orgs/current", input);
  }

  listMembers(): Promise<OrgMemberSummary[]> {
    return this.request("GET", "/v1/orgs/members");
  }

  addMember(input: { email: string; role?: Role }): Promise<OrgMemberSummary> {
    return this.request("POST", "/v1/orgs/members", input);
  }

  updateMemberRole(userId: string, role: Role): Promise<{ user_id: string; role: Role; status: string }> {
    return this.request("PATCH", `/v1/orgs/members/${userId}/role`, { role });
  }

  listServiceAccounts(): Promise<ServiceAccountSummary[]> {
    return this.request("GET", "/v1/orgs/service-accounts");
  }

  createServiceAccount(input: {
    name: string;
    description?: string;
    role?: Role;
  }): Promise<ServiceAccountSummary> {
    return this.request("POST", "/v1/orgs/service-accounts", input);
  }

  listApiKeys(): Promise<ApiKeySummary[]> {
    return this.request("GET", "/v1/orgs/api-keys");
  }

  createApiKey(input: {
    name: string;
    role?: Role;
    service_account_id?: string;
    expires_in_days?: number;
  }): Promise<ApiKeySummary> {
    return this.request("POST", "/v1/orgs/api-keys", input);
  }

  rotateApiKey(keyId: string): Promise<ApiKeySummary> {
    return this.request("POST", `/v1/orgs/api-keys/${keyId}/rotate`);
  }

  revokeApiKey(keyId: string): Promise<{ revoked: boolean }> {
    return this.request("POST", `/v1/orgs/api-keys/${keyId}/revoke`);
  }

  getOrgAuditLogs(limit?: number, offset?: number): Promise<OrgAuditLog[]> {
    return this.request("GET", "/v1/orgs/audit-logs", undefined, { query: { limit, offset } });
  }

  // ---------------------------------------------------------------------------
  // AgentPay Guardian (Governance & Enforcement)
  // ---------------------------------------------------------------------------

  listAgents(status?: string): Promise<AgentIdentity[]> {
    return this.request("GET", "/v1/guardian/agents", undefined, { query: { status } });
  }

  createAgent(input: CreateAgentInput): Promise<AgentIdentity> {
    return this.request("POST", "/v1/guardian/agents", input);
  }

  updateAgentStatus(agentId: string, status: "ACTIVE" | "SUSPENDED" | "REVOKED"): Promise<AgentIdentity> {
    return this.request("PATCH", `/v1/guardian/agents/${agentId}/status`, { status });
  }

  listMerchants(): Promise<Merchant[]> {
    return this.request("GET", "/v1/guardian/merchants");
  }

  createMerchant(input: CreateMerchantInput): Promise<Merchant> {
    return this.request("POST", "/v1/guardian/merchants", input);
  }

  setMerchantAllowlist(merchantId: string, isAllowlisted: boolean): Promise<Merchant> {
    return this.request("PATCH", `/v1/guardian/merchants/${merchantId}/allowlist`, {
      is_allowlisted: isAllowlisted,
    });
  }

  listPassports(params?: { agent_id?: string; status?: PassportStatus }): Promise<SpendingPassport[]> {
    return this.request("GET", "/v1/guardian/passports", undefined, { query: params });
  }

  createPassport(input: CreatePassportInput): Promise<SpendingPassport> {
    return this.request("POST", "/v1/guardian/passports", input);
  }

  updatePassport(passportId: string, input: UpdatePassportInput): Promise<SpendingPassport> {
    return this.request("PATCH", `/v1/guardian/passports/${passportId}`, input);
  }

  revokePassport(passportId: string): Promise<SpendingPassport> {
    return this.request("POST", `/v1/guardian/passports/${passportId}/revoke`);
  }

  listApprovals(params?: {
    status?: ApprovalStatus;
    limit?: number;
    offset?: number;
  }): Promise<ApprovalRecord[]> {
    return this.request("GET", "/v1/guardian/approvals", undefined, { query: params });
  }

  listPayments(params?: {
    state?: PaymentState | string;
    agent_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<PaymentIntent[]> {
    return this.request("GET", "/v1/guardian/payments", undefined, { query: params });
  }

  listPaymentsIterator(params?: {
    state?: PaymentState | string;
    agent_id?: string;
    maxItems?: number;
    pageSize?: number;
  }): AsyncIterableIterator<PaymentIntent> {
    return this.paginate(
      ({ limit, offset }) => this.listPayments({ ...params, limit, offset }),
      { maxItems: params?.maxItems, pageSize: params?.pageSize }
    );
  }

  getPayment(intentId: string): Promise<PaymentIntent> {
    return this.request("GET", `/v1/guardian/payments/${intentId}`);
  }

  getPaymentDetail(intentId: string): Promise<PaymentDetailResponse> {
    return this.request("GET", `/v1/guardian/payments/${intentId}/detail`);
  }

  submitPurchaseProposal(input: SubmitProposalInput): Promise<ProposalSubmissionResponse> {
    return this.request("POST", "/v1/guardian/proposals", {
      ...input,
      merchant_category: input.merchant_category ?? "SOFTWARE",
      currency: (input.currency ?? "USD").toUpperCase(),
      line_items: input.line_items ?? [],
      idempotency_key: input.idempotency_key ?? `tssdk-${crypto.randomUUID()}`,
      quote_expires_in_seconds: input.quote_expires_in_seconds ?? 1800,
    });
  }

  /**
   * Approve a pending purchase proposal.
   * Supports either (intentId, approverId, comment) or (intentId, options: HumanApprovalOptions).
   */
  approveProposal(
    intentId: string,
    approverOrOptions?: string | HumanApprovalOptions,
    comment?: string
  ): Promise<ApprovalActionResponse> {
    let payload: { approver_id?: string; approved: boolean; comment?: string };

    if (typeof approverOrOptions === "object" && approverOrOptions !== null) {
      payload = {
        approver_id: approverOrOptions.approver_id,
        approved: approverOrOptions.approved ?? true,
        comment: approverOrOptions.comment,
      };
    } else {
      payload = {
        approver_id: approverOrOptions,
        approved: true,
        comment,
      };
    }

    return this.request("POST", `/v1/guardian/proposals/${intentId}/approve`, payload);
  }

  rejectProposal(intentId: string, approverId?: string, comment?: string): Promise<ApprovalActionResponse> {
    return this.request("POST", `/v1/guardian/proposals/${intentId}/approve`, {
      approver_id: approverId,
      approved: false,
      comment,
    });
  }

  initiateCheckout(
    intentId: string,
    input?: { attempt_number?: number; idempotency_key?: string; return_url?: string; cancel_url?: string }
  ): Promise<CheckoutResponse> {
    return this.request("POST", `/v1/guardian/payments/${intentId}/checkout`, {
      attempt_number: input?.attempt_number ?? 1,
      idempotency_key: input?.idempotency_key ?? `chk-${crypto.randomUUID()}`,
      return_url: input?.return_url,
      cancel_url: input?.cancel_url,
    });
  }

  markBuyerApproved(intentId: string, attemptId: string, payerId?: string): Promise<{ status: string; payment_intent_id: string }> {
    return this.request("POST", `/v1/guardian/payments/${intentId}/buyer-approved`, {
      attempt_id: attemptId,
      payer_id: payerId,
    });
  }

  executeCapture(intentId: string, attemptId: string): Promise<PaymentAttempt> {
    return this.request("POST", `/v1/guardian/payments/${intentId}/capture`, {
      attempt_id: attemptId,
    });
  }

  markBuyerDeclined(intentId: string, attemptId: string, reason?: string): Promise<PaymentAttempt> {
    return this.request("POST", `/v1/guardian/payments/${intentId}/buyer-declined`, {
      attempt_id: attemptId,
      reason: reason ?? "Buyer cancelled checkout",
    });
  }

  reconcilePayment(intentId: string, attemptId: string): Promise<PaymentAttempt> {
    return this.request("POST", `/v1/guardian/payments/${intentId}/reconcile`, {
      attempt_id: attemptId,
    });
  }

  // ---------------------------------------------------------------------------
  // GhostPay (Replay, Counterfactual Simulation, DNA, Investigations)
  // ---------------------------------------------------------------------------

  getGhostPayHealth(): Promise<{ status: string; service: string }> {
    return this.request("GET", "/v1/ghostpay/health");
  }

  ingestTrace(trace: Record<string, unknown>): Promise<PaymentTrace> {
    return this.request("POST", "/v1/ghostpay/traces/ingest", trace);
  }

  getTrace(traceId: string): Promise<PaymentTrace> {
    return this.request("GET", `/v1/ghostpay/traces/${traceId}`);
  }

  getTraceTimeline(traceId: string): Promise<ReplayTimelineEntry[]> {
    return this.request("GET", `/v1/ghostpay/traces/${traceId}/timeline`);
  }

  replay(request: ReplayRequest): Promise<ReplayResult> {
    return this.request("POST", "/v1/ghostpay/replay", request);
  }

  replayByPayment(
    intentId: string,
    options?: { policy_version?: string; persist_investigation?: boolean }
  ): Promise<ReplayResult> {
    return this.request("POST", `/v1/ghostpay/replay/by-payment/${intentId}`, {
      policy_version: options?.policy_version,
      persist_investigation: options?.persist_investigation ?? true,
    });
  }

  comparePolicy(input: {
    payment_intent_id: string;
    source_policy_version: string;
    target_policy_version: string;
  }): Promise<PolicyComparisonReport> {
    return this.request("POST", "/v1/ghostpay/replay/compare", input);
  }

  simulate(input: { request: ReplayRequest; overrides?: Record<string, unknown> }): Promise<ReplayResult> {
    return this.request("POST", "/v1/ghostpay/simulate", input);
  }

  simulateByPayment(
    intentId: string,
    overrides: Record<string, unknown>,
    persistInvestigation = true,
    policyVersion?: string
  ): Promise<ReplayResult> {
    return this.request("POST", `/v1/ghostpay/simulate/by-payment/${intentId}`, {
      overrides,
      persist_investigation: persistInvestigation,
      policy_version: policyVersion,
    });
  }

  simulateCounterfactual(input: {
    request: ReplayRequest;
    overrides?: Record<string, unknown>;
  }): Promise<ReplayResult> {
    return this.request("POST", "/v1/ghostpay/counterfactual", input);
  }

  getTimeline(input: { request: ReplayRequest }): Promise<ReplayTimelineEntry[]> {
    return this.request("POST", "/v1/ghostpay/timeline", input);
  }

  getTimelineByPayment(intentId: string): Promise<ReplayTimelineEntry[]> {
    return this.request("GET", `/v1/ghostpay/timeline/by-payment/${intentId}`);
  }

  getAgentProfile(agentId: string): Promise<AgentBehaviorProfile> {
    return this.request("GET", `/v1/ghostpay/agents/${agentId}/profile`);
  }

  analyzeAgentDna(agentId: string, windowDays?: number): Promise<AgentDNAAnomalyResult> {
    return this.request("POST", `/v1/ghostpay/agents/${agentId}/analyze`, {
      window_days: windowDays ?? 30,
    });
  }

  listInvestigations(params?: {
    payment_intent_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<InvestigationListResponse> {
    return this.request("GET", "/v1/ghostpay/investigations", undefined, { query: params });
  }

  listInvestigationsIterator(params?: {
    payment_intent_id?: string;
    maxItems?: number;
  }): AsyncIterableIterator<InvestigationReport> {
    return this.paginate(
      ({ limit, offset }) => this.listInvestigations({ ...params, limit, offset }),
      { maxItems: params?.maxItems }
    );
  }

  createInvestigation(input: {
    payment_intent_id: string;
    title: string;
    findings?: string[];
    replay_result?: ReplayResult;
  }): Promise<InvestigationReport> {
    return this.request("POST", "/v1/ghostpay/investigations", input);
  }

  getInvestigation(investigationId: string): Promise<InvestigationReport> {
    return this.request("GET", `/v1/ghostpay/investigations/${investigationId}`);
  }

  getInvestigationEvidence(investigationId: string): Promise<DisputeOSEvidenceBundle> {
    return this.request("GET", `/v1/ghostpay/investigations/${investigationId}/evidence`);
  }

  // ---------------------------------------------------------------------------
  // DisputeOS (Evidence Graphs, Disputes, Contradictions, AI Summaries)
  // ---------------------------------------------------------------------------

  listDisputes(): Promise<DisputeCase[]> {
    return this.request("GET", "/v1/disputeos/cases");
  }

  createDispute(input: CreateDisputeCaseInput): Promise<DisputeCase> {
    return this.request("POST", "/v1/disputeos/cases", input);
  }

  seedDemoDispute(preset?: string): Promise<DisputeCaseDetailResponse> {
    return this.request("POST", "/v1/disputeos/cases/seed-demo", undefined, {
      query: { preset },
    });
  }

  getDispute(caseId: string): Promise<DisputeCaseDetailResponse> {
    return this.request("GET", `/v1/disputeos/cases/${caseId}`);
  }

  attachEvidence(caseId: string, input: AttachEvidenceInput): Promise<AttachEvidenceResponse> {
    return this.request("POST", `/v1/disputeos/cases/${caseId}/evidence`, input);
  }

  uploadArtifact(
    caseId: string,
    file: Blob | Uint8Array | string,
    filename = "evidence.pdf",
    sourceRef = "manual_upload"
  ): Promise<AttachEvidenceResponse> {
    const formData = new FormData();
    const blob = file instanceof Blob ? file : new Blob([file as unknown as BlobPart]);
    formData.append("file", blob, filename);
    formData.append("source_ref", sourceRef);

    return this.request("POST", `/v1/disputeos/cases/${caseId}/artifacts`, formData);
  }

  async getArtifact(caseId: string, artifactId: string): Promise<ArrayBuffer> {
    const url = `${this.baseUrl}/v1/disputeos/cases/${caseId}/artifacts/${artifactId}`;
    const headers: Record<string, string> = {};
    if (this.bearerToken) {
      headers.Authorization = `Bearer ${this.bearerToken}`;
    } else if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    }
    if (this.organizationId) {
      headers["X-Org-Id"] = this.organizationId;
    }

    const resp = await this.fetchImpl(url, { headers });
    if (!resp.ok) {
      const text = await resp.text();
      let parsed: unknown = text;
      try {
        parsed = JSON.parse(text);
      } catch {
        // noop
      }
      const extracted = extractFastAPIError(parsed, resp.statusText, resp.status);
      throw new AegisAPIError(resp.status, extracted.message, parsed, extracted.errorCode);
    }
    return resp.arrayBuffer();
  }

  assignDispute(caseId: string, assignedTo: string): Promise<{ case_id: string; assigned_to: string }> {
    return this.request("POST", `/v1/disputeos/cases/${caseId}/assign`, {
      assigned_to: assignedTo,
    });
  }

  addDisputeNote(caseId: string, body: string): Promise<{ id: string; case_id: string; body: string }> {
    return this.request("POST", `/v1/disputeos/cases/${caseId}/notes`, { body });
  }

  analyzeDispute(caseId: string): Promise<DisputeCaseDetailResponse> {
    return this.request("POST", `/v1/disputeos/cases/${caseId}/analyze`);
  }

  getDisputeReport(caseId: string): Promise<DisputeReport> {
    return this.request("GET", `/v1/disputeos/cases/${caseId}/report`);
  }

  approveDisputeResponse(
    caseId: string,
    input: { approver_id: string; draft_response_text: string }
  ): Promise<DisputeCase> {
    return this.request("POST", `/v1/disputeos/cases/${caseId}/approve`, input);
  }

  submitDisputeToPayPal(caseId: string, draftResponseText?: string): Promise<SubmitDisputeResponse> {
    return this.request("POST", `/v1/disputeos/cases/${caseId}/submit`, {
      draft_response_text: draftResponseText,
    });
  }

  // ---------------------------------------------------------------------------
  // Settings, Webhooks, Outbox / DLQ
  // ---------------------------------------------------------------------------

  listWebhookEndpoints(): Promise<WebhookEndpoint[]> {
    return this.request("GET", "/v1/webhooks/endpoints");
  }

  createWebhookEndpoint(input: CreateWebhookEndpointInput): Promise<WebhookEndpoint> {
    return this.request("POST", "/v1/webhooks/endpoints", input);
  }

  deleteWebhookEndpoint(endpointId: string): Promise<{ deleted: boolean; id: string }> {
    return this.request("DELETE", `/v1/webhooks/endpoints/${endpointId}`);
  }

  listWebhookDeliveries(params?: {
    status?: "DELIVERED" | "FAILED" | "PENDING";
    limit?: number;
    offset?: number;
  }): Promise<WebhookDelivery[]> {
    return this.request("GET", "/v1/webhooks/deliveries", undefined, { query: params });
  }

  listWebhookDeliveriesIterator(params?: {
    status?: "DELIVERED" | "FAILED" | "PENDING";
    maxItems?: number;
  }): AsyncIterableIterator<WebhookDelivery> {
    return this.paginate(
      ({ limit, offset }) => this.listWebhookDeliveries({ ...params, limit, offset }),
      { maxItems: params?.maxItems }
    );
  }

  listOutboxEvents(params?: {
    status?: "PENDING" | "PROCESSING" | "DELIVERED" | "DEAD_LETTER";
    limit?: number;
    offset?: number;
  }): Promise<OutboxEvent[]> {
    return this.request("GET", "/v1/worker/outbox", undefined, { query: params });
  }

  listOutboxEventsIterator(params?: {
    status?: "PENDING" | "PROCESSING" | "DELIVERED" | "DEAD_LETTER";
    maxItems?: number;
  }): AsyncIterableIterator<OutboxEvent> {
    return this.paginate(
      ({ limit, offset }) => this.listOutboxEvents({ ...params, limit, offset }),
      { maxItems: params?.maxItems }
    );
  }

  requeueOutboxEvent(outboxId: string): Promise<OutboxEvent> {
    return this.request("POST", `/v1/worker/outbox/${outboxId}/requeue`);
  }
}
