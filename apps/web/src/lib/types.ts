declare global {
  function truncateId(val?: string | null, len?: number): string;
  interface URLSearchParams {
    get(name: string): string;
  }
}

export type Role = "OWNER" | "ADMIN" | "OPERATOR" | "AUDITOR" | "AGENT_SERVICE" | "VIEWER";

export const CANONICAL_ROLES: Role[] = [
  "OWNER",
  "ADMIN",
  "OPERATOR",
  "AUDITOR",
  "AGENT_SERVICE",
  "VIEWER",
];

export type PaymentState =
  | "CREATED"
  | "POLICY_CHECK"
  | "AWAITING_APPROVAL"
  | "APPROVED"
  | "CHECKOUT_READY"
  | "CHECKOUT_CREATED"
  | "AWAITING_PAYPAL_BUYER"
  | "BUYER_APPROVED"
  | "CAPTURE_PENDING"
  | "CAPTURED"
  | "CAPTURE_IN_PROGRESS"
  | "SUCCEEDED"
  | "FAILED"
  | "PENDING_PROVIDER"
  | "CANCELLED"
  | "EXPIRED"
  | "REFUNDED"
  | "PROPOSED"
  | "POLICY_EVALUATED"
  | "REJECTED";

export interface PaginationParams {
  limit?: number;
  offset?: number;
  q?: string;
}

export interface PaginatedResult<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListPaymentsParams extends PaginationParams {
  state?: PaymentState | string;
  agent_id?: string;
  merchant_id?: string;
}

export interface ListAgentsParams extends PaginationParams {
  status?: string;
}

export interface ListMerchantsParams extends PaginationParams {
  allowlisted?: boolean;
}

export interface ListPassportsParams extends PaginationParams {
  status?: string;
  agent_id?: string;
}

export interface ListDisputesParams extends PaginationParams {
  status?: string;
}

export interface ListAuditEventsParams extends PaginationParams {
  event_type?: string;
  actor_id?: string;
  payment_intent_id?: string;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  role: Role;
  created_at: string;
}

export interface AuthSession {
  access_token?: string; // Stored in HttpOnly cookie; optional on client
  token_type?: string;
  user_id: string;
  email: string;
  full_name: string;
  active_tenant_id: string;
  active_role: Role;
  permissions: string[];
  organizations: OrganizationSummary[];
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
  previous_event_hash: string | null;
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
  status: "ACTIVE" | "SUSPENDED" | "REVOKED";
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
  status: "ACTIVE" | "PAUSED" | "REVOKED" | "EXPIRED";
  expires_at: string;
  created_at: string;
}

export interface VerifiedPayPalCapture {
  paypal_order_id: string;
  paypal_capture_id: string;
  paypal_status: string;
  verified_amount_minor: number;
  verified_currency: string;
  verification_hash: string;
  verified_at: string;
}

export interface PaymentAttemptRecord {
  id: string;
  attempt_number: number;
  state: PaymentState;
  provider: string;
  paypal_order_id: string | null;
  paypal_approval_url: string | null;
  verified_capture: VerifiedPayPalCapture | null;
  failure_code: string | null;
  failure_reason: string | null;
  created_at: string;
}

export interface ApprovalRecord {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  decision_id: string;
  approver_id: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "CONSUMED";
  bound_merchant_id: string;
  bound_amount_minor: number;
  bound_currency: string;
  bound_quote_hash: string;
  comment: string | null;
  expires_at: string;
  decided_at: string | null;
  consumed_at: string | null;
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
  state: PaymentState;
  idempotency_key: string;
  authorization_decision_id: string | null;
  approval_record_id: string | null;
  reservation_id: string | null;
  active_attempt_id: string | null;
  attempts?: PaymentAttemptRecord[];
  active_attempt?: PaymentAttemptRecord | null;
  approval?: ApprovalRecord | null;
  created_at: string;
  updated_at: string;
}

export interface ReplayTimelineEntry {
  sequence_number: number;
  event_id?: string;
  event_type: string;
  actor_type: string;
  actor_id: string;
  occurred_at: string;
  summary?: string;
  evidence_ids?: string[];
  integrity_verified?: boolean;
  event_hash?: string | null;
  previous_event_hash?: string | null;
  // UI compatibility aliases for existing page components
  actor?: string;
  source?: string;
  timestamp?: string;
}

export interface ReplayResultRecord {
  replay_id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  policy_version: string;
  original_outcome: "ALLOW" | "DENY" | "ESCALATE";
  recomputed_outcome: "ALLOW" | "DENY" | "ESCALATE";
  original_reason_codes: string[];
  recomputed_reason_codes: string[];
  changed_constraints: string[];
  drift_detected: boolean;
  explanation: string;
  anomalies: string[];
  missing_evidence: string[];
  integrity_valid: boolean;
  consistency_status: "CONSISTENT" | "DRIFT_DETECTED" | "INTEGRITY_FAILURE" | "INCOMPLETE_EVIDENCE";
  executed_payment: boolean;
  replayed_at: string;
  timeline: ReplayTimelineEntry[];
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

export interface AgentDNAProfile {
  agent_id: string;
  tenant_id: string;
  name: string;
  profile_version: string;
  risk_score: number;
  merchant_affinities: Array<{ merchant_id: string; count: number; total_minor: number }>;
  spending_entropy: number;
  anomaly_count: number;
  drift_indicators: string[];
  last_updated: string;
}

export interface DisputeCitation {
  claim: string;
  evidence_id: string;
  verbatim_excerpt: string;
  verified: boolean;
}

export interface DisputeAnalysis {
  id: string;
  tenant_id: string;
  correlation_id: string;
  dispute_case_id: string;
  is_synthetic: boolean;
  recommendation: string;
  confidence_score: number;
  agent_authorized: boolean;
  agent_followed_policy: boolean;
  merchant_fulfilled_order?: boolean | null;
  contradictions: string[];
  missing_evidence: string[];
  citations: DisputeCitation[];
  rejected_claims: string[];
  recommended_actions: string[];
  grounded_summary: string;
  draft_response_text: string;
  requires_human_approval: boolean;
  generated_with_llm: boolean;
  analyzed_at: string;
}

export interface DisputeCaseRecord {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  paypal_dispute_id: string | null;
  source_type: "PAYPAL_SANDBOX" | "SYNTHETIC_DEMO" | "MANUAL";
  is_synthetic: boolean;
  reason: string;
  buyer_claim: string;
  amount_minor: number;
  currency: string;
  status: "OPEN" | "UNDER_INVESTIGATION" | "DRAFT_READY" | "APPROVED_FOR_SUBMISSION" | "SUBMITTED" | "RESOLVED";
  evidence_ids: string[];
  human_approved_for_submission: boolean;
  approved_by: string | null;
  approved_at: string | null;
  response_due_by?: string | null;
  response_payload_hash?: string | null;
  opened_at: string;
  updated_at: string;
  analysis?: DisputeAnalysis | null;
}

export interface WebhookEndpointRecord {
  id: string;
  tenant_id: string;
  url: string;
  description: string;
  secret: string;
  event_types: string[];
  is_active: boolean;
  created_at: string;
}

export interface WebhookDeliveryRecord {
  id: string;
  endpoint_id: string;
  event_type: string;
  status_code: number | null;
  delivered_at: string;
  error_message: string | null;
}

export interface OutboxMessageRecord {
  id: string;
  event_type: string;
  status: "PENDING" | "PROCESSING" | "SENT" | "DEAD_LETTER";
  retry_count: number;
  payload: Record<string, unknown>;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ServiceAccountRecord {
  id: string;
  tenant_id: string;
  name: string;
  role: Role;
  created_at: string;
  last_used_at: string | null;
}

export interface MemberRecord {
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
  joined_at: string;
}

export interface ApiKeyRecord {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  expires_at: string | null;
  revoked: boolean;
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
