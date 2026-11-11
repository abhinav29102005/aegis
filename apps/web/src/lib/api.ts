export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  role: string;
  created_at: string;
}

export interface AuthSession {
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

export interface OverviewMetrics {
  tenant_id: string;
  agents: { total: number; active: number };
  budget: {
    total_budget_minor: number;
    spent_minor: number;
    reserved_minor: number;
    available_minor: number;
  };
  payments: {
    total: number;
    by_state: Record<string, number>;
  };
  pending_approvals: number;
  open_disputes: number;
  risk_alerts: number;
  dead_letter_outbox: number;
  recent_events: FinancialEventRecord[];
}

export interface FinancialEventRecord {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string | null;
  sequence_number: number;
  event_type: string;
  actor_type: string;
  actor_id: string;
  previous_hash: string;
  event_hash: string;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface AgentRecord {
  id: string;
  tenant_id: string;
  name: string;
  purpose: string;
  framework: string;
  status: string;
  public_fingerprint: string;
  created_at: string;
}

export interface MerchantRecord {
  id: string;
  tenant_id: string;
  name: string;
  domain: string;
  category: string;
  paypal_merchant_id: string | null;
  is_allowlisted: boolean;
  is_sandbox_verified: boolean;
  created_at: string;
}

export interface PassportRecord {
  id: string;
  tenant_id: string;
  agent_id: string;
  policy_version: string;
  currency: string;
  total_budget_minor: number;
  spent_minor: number;
  reserved_minor: number;
  per_tx_limit_minor: number;
  daily_limit_minor: number;
  human_approval_threshold_minor: number;
  allowed_merchant_ids: string[];
  allowed_categories: string[];
  allow_unknown_merchants: boolean;
  status: string;
  expires_at: string;
  created_at: string;
}

export interface PaymentIntentRecord {
  id: string;
  tenant_id: string;
  correlation_id: string;
  proposal_id: string;
  agent_id: string;
  passport_id: string;
  merchant_id: string;
  quote_snapshot_id: string;
  quote_hash: string;
  amount_minor: number;
  currency: string;
  state: string;
  idempotency_key: string;
  authorization_decision_id: string | null;
  approval_record_id: string | null;
  reservation_id: string | null;
  active_attempt_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvestigationRecord {
  id: string;
  tenant_id: string;
  payment_intent_id: string;
  correlation_id: string;
  mode: string;
  policy_version: string;
  original_outcome: string;
  recomputed_outcome: string;
  consistency_status: string;
  drift_detected: boolean;
  integrity_valid: boolean;
  anomalies: string[];
  overrides: Record<string, unknown>;
  created_by: string;
  created_at: string;
}

export interface ReplayResultRecord {
  replay_id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  policy_version: string;
  original_outcome: string;
  recomputed_outcome: string;
  original_reason_codes: string[];
  recomputed_reason_codes: string[];
  changed_constraints: string[];
  drift_detected: boolean;
  explanation: string;
  anomalies: string[];
  missing_evidence: string[];
  integrity_valid: boolean;
  consistency_status: string;
  executed_payment: boolean;
  timeline: Array<{
    sequence_number: number;
    timestamp: string;
    source: string;
    event_type: string;
    actor: string;
    summary: string;
  }>;
}

export interface DisputeCaseRecord {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  paypal_dispute_id: string | null;
  source_type: string;
  is_synthetic: boolean;
  reason: string;
  buyer_claim: string;
  amount_minor: number;
  currency: string;
  status: string;
  evidence_ids: string[];
  human_approved_for_submission: boolean;
  approved_by: string | null;
  approved_at: string | null;
  opened_at: string;
  updated_at: string;
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
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

export async function apiRequest<T>(
  path: string,
  options: {
    method?: string;
    token?: string | null;
    orgId?: string | null;
    body?: unknown;
    isFormData?: boolean;
  } = {},
): Promise<T> {
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

  const resp = await fetch(`${getApiBaseUrl()}${path}`, {
    method: options.method ?? "GET",
    headers,
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
    let msg = `HTTP ${resp.status}`;
    if (parsed && typeof parsed === "object") {
      const obj = parsed as Record<string, unknown>;
      if (typeof obj.message === "string") msg = obj.message;
      else if (typeof obj.detail === "string") msg = obj.detail;
      else if (obj.detail && typeof obj.detail === "object" && "message" in obj.detail) {
        msg = String((obj.detail as { message: unknown }).message);
      }
    }
    throw new ApiClientError(resp.status, msg, parsed);
  }
  return parsed as T;
}
