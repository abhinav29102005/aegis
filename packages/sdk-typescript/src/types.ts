/**
 * Canonical domain contracts, enums, and request/response models for AEGIS SDK.
 * Matches packages/contracts, packages/security, and services/api schemas.
 */

// ---------------------------------------------------------------------------
// Canonical Enums & Constants
// ---------------------------------------------------------------------------

/**
 * Canonical tenant roles (6 roles).
 */
export type Role =
  | "OWNER"
  | "ADMIN"
  | "OPERATOR"
  | "AUDITOR"
  | "AGENT_SERVICE"
  | "VIEWER";

export const Roles: Record<Role, Role> = {
  OWNER: "OWNER",
  ADMIN: "ADMIN",
  OPERATOR: "OPERATOR",
  AUDITOR: "AUDITOR",
  AGENT_SERVICE: "AGENT_SERVICE",
  VIEWER: "VIEWER",
} as const;

/**
 * Canonical payment state machine (11 states).
 */
export type PaymentState =
  | "CREATED"
  | "POLICY_CHECK"
  | "AWAITING_APPROVAL"
  | "CHECKOUT_READY"
  | "AWAITING_PAYPAL_BUYER"
  | "CAPTURE_PENDING"
  | "SUCCEEDED"
  | "FAILED"
  | "PENDING_PROVIDER"
  | "CANCELLED";

export const PaymentStates: Record<PaymentState, PaymentState> = {
  CREATED: "CREATED",
  POLICY_CHECK: "POLICY_CHECK",
  AWAITING_APPROVAL: "AWAITING_APPROVAL",
  CHECKOUT_READY: "CHECKOUT_READY",
  AWAITING_PAYPAL_BUYER: "AWAITING_PAYPAL_BUYER",
  CAPTURE_PENDING: "CAPTURE_PENDING",
  SUCCEEDED: "SUCCEEDED",
  FAILED: "FAILED",
  PENDING_PROVIDER: "PENDING_PROVIDER",
  CANCELLED: "CANCELLED",
} as const;

/**
 * Deterministic policy decision outcome.
 */
export type DecisionOutcome = "ALLOW" | "DENY" | "ESCALATE";

export const DecisionOutcomes: Record<DecisionOutcome, DecisionOutcome> = {
  ALLOW: "ALLOW",
  DENY: "DENY",
  ESCALATE: "ESCALATE",
} as const;

export type DecisionReasonCode =
  | "OK_WITHIN_POLICY"
  | "DENIED_EXCEEDS_PER_TX_LIMIT"
  | "DENIED_EXCEEDS_PASSPORT_BUDGET"
  | "DENIED_EXCEEDS_DAILY_LIMIT"
  | "DENIED_MERCHANT_NOT_ALLOWLISTED"
  | "DENIED_CATEGORY_NOT_ALLOWED"
  | "DENIED_PASSPORT_EXPIRED"
  | "DENIED_PASSPORT_REVOKED"
  | "DENIED_AGENT_SUSPENDED"
  | "DENIED_APPROVAL_EXPIRED"
  | "DENIED_APPROVAL_MISMATCH"
  | "DENIED_QUOTE_EXPIRED"
  | "DENIED_INSUFFICIENT_BUDGET"
  | "DENIED_CROSS_TENANT"
  | "ESCALATED_REQUIRES_HUMAN_APPROVAL"
  | "ESCALATED_UNKNOWN_MERCHANT"
  | "ESCALATED_HIGH_RISK_AMOUNT";

export type PassportStatus = "ACTIVE" | "PAUSED" | "REVOKED" | "EXPIRED";
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "CONSUMED";
export type ReservationStatus = "HELD" | "CAPTURED" | "RELEASED" | "EXPIRED";

export type FinancialEventType =
  | "PROPOSAL_CREATED"
  | "POLICY_EVALUATED"
  | "APPROVAL_REQUESTED"
  | "HUMAN_APPROVED"
  | "HUMAN_REJECTED"
  | "BUDGET_RESERVED"
  | "BUDGET_RELEASED"
  | "BUDGET_CAPTURED"
  | "PAYPAL_ORDER_CREATED"
  | "PAYPAL_BUYER_APPROVED"
  | "PAYPAL_BUYER_CANCELLED"
  | "PAYPAL_CAPTURE_REQUESTED"
  | "PAYPAL_CAPTURE_VERIFIED"
  | "PAYPAL_TIMEOUT_PENDING"
  | "PAYPAL_WEBHOOK_RECEIVED"
  | "PAYMENT_FAILED"
  | "DISPUTE_OPENED"
  | "DISPUTE_ANALYZED"
  | "DISPUTE_RESPONSE_APPROVED";

export type EvidenceSourceType =
  | "PROPOSAL"
  | "QUOTE"
  | "POLICY_DECISION"
  | "HUMAN_APPROVAL"
  | "PAYPAL_ORDER"
  | "PAYPAL_CAPTURE"
  | "PAYPAL_WEBHOOK"
  | "CARRIER_TRACKING"
  | "DELIVERY_RECEIPT"
  | "CUSTOMER_MESSAGE"
  | "SYNTHETIC_FIXTURE";

export type DisputeSourceType = "PAYPAL_SANDBOX" | "SYNTHETIC_DEMO";
export type DisputeStatus =
  | "OPEN"
  | "UNDER_INVESTIGATION"
  | "DRAFT_READY"
  | "APPROVED_FOR_SUBMISSION"
  | "SUBMITTED"
  | "RESOLVED";

export type DisputeRecommendation =
  | "CHALLENGE_WITH_EVIDENCE"
  | "OFFER_PARTIAL_OR_RETURN"
  | "ACCEPT_AND_REFUND"
  | "NEED_MORE_EVIDENCE";

// ---------------------------------------------------------------------------
// Base & Platform Models
// ---------------------------------------------------------------------------

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  role: Role | string;
  created_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  full_name: string;
  active_tenant_id: string;
  active_role: Role | string;
  permissions: string[];
  organizations: OrganizationSummary[];
}

export interface UserMeResponse {
  user_id: string;
  email: string;
  full_name: string;
  actor_type: string;
  actor_id: string;
  role: Role | string;
  tenant_id: string;
  permissions: string[];
  organizations: OrganizationSummary[];
}

export interface OrgMemberSummary {
  user_id: string;
  email: string;
  full_name: string;
  role: Role | string;
  status: string;
  created_at: string;
}

export interface ServiceAccountSummary {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  role: Role | string;
  status: string;
  created_at: string;
  last_used_at?: string | null;
}

export interface ApiKeySummary {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  role: Role | string;
  service_account_id?: string | null;
  status: string;
  expires_at?: string | null;
  last_used_at?: string | null;
  created_at: string;
  raw_key?: string; // only returned upon creation
}

export interface OrgAuditLog {
  id: string;
  tenant_id: string;
  actor_type: string;
  actor_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface OverviewMetrics {
  total_spend_minor: number;
  total_spend_usd: number;
  active_agents_count: number;
  open_disputes_count: number;
  pending_approvals_count: number;
  recent_payments_count: number;
  currency: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Guardian Models
// ---------------------------------------------------------------------------

export interface AgentIdentity {
  id: string;
  tenant_id: string;
  name: string;
  purpose: string;
  framework: string;
  status: "ACTIVE" | "SUSPENDED" | "REVOKED";
  public_fingerprint: string;
  created_at: string;
  schema_version?: string;
}

export interface Merchant {
  id: string;
  tenant_id: string;
  name: string;
  domain: string;
  category: string;
  paypal_merchant_id?: string | null;
  is_allowlisted: boolean;
  is_sandbox_verified: boolean;
  created_at: string;
  schema_version?: string;
}

export interface SpendingPassport {
  id: string;
  tenant_id: string;
  agent_id: string;
  policy_version: string;
  currency: string;
  total_budget_minor: number;
  spent_minor: number;
  reserved_minor: number;
  available_budget_minor?: number;
  per_tx_limit_minor: number;
  daily_limit_minor: number;
  human_approval_threshold_minor: number;
  allowed_merchant_ids: string[];
  allowed_categories: string[];
  allow_unknown_merchants: boolean;
  status: PassportStatus;
  expires_at: string;
  created_at: string;
  schema_version?: string;
}

export interface PurchaseProposal {
  id: string;
  tenant_id: string;
  correlation_id: string;
  agent_id: string;
  passport_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_category: string;
  amount_minor: number;
  currency: string;
  item_summary: string;
  line_items: Array<Record<string, unknown>>;
  rationale: string;
  idempotency_key: string;
  proposed_by_model: string;
  created_at: string;
  schema_version?: string;
}

export interface QuoteSnapshot {
  id: string;
  tenant_id: string;
  correlation_id: string;
  proposal_id: string;
  merchant_id: string;
  amount_minor: number;
  currency: string;
  line_items: Array<Record<string, unknown>>;
  quote_hash: string;
  expires_at: string;
  created_at: string;
  schema_version?: string;
}

export interface AuthorizationDecision {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  proposal_id: string;
  passport_id: string;
  quote_snapshot_id: string;
  quote_hash: string;
  policy_version: string;
  outcome: DecisionOutcome;
  reason_codes: DecisionReasonCode[];
  violated_constraints: string[];
  requires_human_approval: boolean;
  explanation: string;
  policy_inputs: Record<string, unknown>;
  decided_at: string;
  schema_version?: string;
}

export interface ApprovalRecord {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  decision_id: string;
  approver_id: string;
  status: ApprovalStatus;
  bound_merchant_id: string;
  bound_amount_minor: number;
  bound_currency: string;
  bound_quote_hash: string;
  comment?: string | null;
  expires_at: string;
  decided_at?: string | null;
  consumed_at?: string | null;
  created_at: string;
  schema_version?: string;
}

export interface BudgetReservation {
  id: string;
  tenant_id: string;
  correlation_id: string;
  passport_id: string;
  payment_intent_id: string;
  amount_minor: number;
  currency: string;
  status: ReservationStatus;
  expires_at: string;
  created_at: string;
  updated_at: string;
  schema_version?: string;
}

export interface PayPalBuyerApproval {
  paypal_order_id: string;
  payer_id?: string | null;
  buyer_status: string;
  approved_at: string;
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

export interface PaymentAttempt {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  attempt_number: number;
  idempotency_key: string;
  provider: string;
  paypal_order_id?: string | null;
  paypal_approval_url?: string | null;
  buyer_approval?: PayPalBuyerApproval | null;
  verified_capture?: VerifiedPayPalCapture | null;
  state: PaymentState;
  failure_code?: string | null;
  failure_reason?: string | null;
  created_at: string;
  updated_at: string;
  schema_version?: string;
}

export interface PaymentIntent {
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
  authorization_decision_id?: string | null;
  approval_record_id?: string | null;
  reservation_id?: string | null;
  active_attempt_id?: string | null;
  created_at: string;
  updated_at: string;
  schema_version?: string;
}

export interface ProposalSubmissionResponse {
  payment_intent: PaymentIntent;
  decision: AuthorizationDecision;
}

export interface ApprovalActionResponse {
  payment_intent: PaymentIntent;
  approval: ApprovalRecord;
}

export interface CheckoutResponse {
  payment_intent: PaymentIntent;
  attempt: PaymentAttempt;
  approval_url?: string | null;
}

export interface PaymentDetailResponse {
  intent: PaymentIntent;
  proposal?: PurchaseProposal | null;
  quote?: QuoteSnapshot | null;
  decision?: AuthorizationDecision | null;
  approval?: ApprovalRecord | null;
  reservation?: BudgetReservation | null;
  attempts?: PaymentAttempt[];
  timeline?: ReplayTimelineEntry[];
}

// ---------------------------------------------------------------------------
// GhostPay & Replay Models
// ---------------------------------------------------------------------------

export interface FinancialEvent {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id?: string | null;
  sequence_number: number;
  event_type: FinancialEventType;
  actor_type: string;
  actor_id: string;
  payload: Record<string, unknown>;
  previous_event_hash?: string | null;
  event_hash: string;
  occurred_at: string;
  schema_version?: string;
}

export interface EvidenceRecord {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id?: string | null;
  dispute_case_id?: string | null;
  source_type: EvidenceSourceType;
  source_ref: string;
  title: string;
  content: Record<string, unknown>;
  content_hash: string;
  is_synthetic: boolean;
  collected_at: string;
  schema_version?: string;
}

export interface ReplayTimelineEntry {
  sequence_number: number;
  event_id: string;
  event_type: FinancialEventType;
  actor_type: string;
  actor_id: string;
  occurred_at: string;
  summary: string;
  evidence_ids: string[];
  integrity_verified: boolean;
  schema_version?: string;
}

export interface ReplayRequest {
  tenant_id?: string;
  correlation_id?: string;
  payment_intent: PaymentIntent;
  proposal: PurchaseProposal;
  quote_snapshot: QuoteSnapshot;
  recorded_passport: SpendingPassport;
  recorded_merchant: Merchant;
  recorded_decision: AuthorizationDecision;
  approval_record?: ApprovalRecord | null;
  policy_version?: string;
  events?: FinancialEvent[];
  evidence_records?: EvidenceRecord[];
  counterfactual_overrides?: Record<string, unknown>;
  evaluation_time?: string | null;
}

export interface ReplayResult {
  replay_id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  policy_version: string;
  timeline: ReplayTimelineEntry[];
  original_outcome: DecisionOutcome;
  recomputed_outcome: DecisionOutcome;
  original_reason_codes: DecisionReasonCode[];
  recomputed_reason_codes: DecisionReasonCode[];
  changed_constraints: string[];
  drift_detected: boolean;
  explanation: string;
  evidence_references: string[];
  missing_evidence: string[];
  anomalies: string[];
  integrity_valid: boolean;
  consistency_status: "CONSISTENT" | "DRIFT_DETECTED" | "INTEGRITY_FAILURE" | "INCOMPLETE_EVIDENCE";
  executed_payment: boolean;
  replayed_at: string;
  schema_version?: string;
}

export interface PolicyComparisonReport {
  intent_id: string;
  original_policy_version: string;
  target_policy_version: string;
  original_outcome: DecisionOutcome;
  target_outcome: DecisionOutcome;
  difference_summary: string;
  [key: string]: unknown;
}

export interface PaymentTrace {
  trace_id: string;
  tenant_id: string;
  payment_intent_id: string;
  captured_at: string;
  events: FinancialEvent[];
  [key: string]: unknown;
}

export interface AgentBehaviorProfile {
  agent_id: string;
  tenant_id: string;
  total_proposals: number;
  approval_rate: number;
  average_amount_minor: number;
  frequent_merchants: Array<{ merchant_id: string; count: number }>;
  risk_score: number;
  last_activity_at: string;
}

export interface AgentDNAAnomalyResult {
  agent_id: string;
  is_anomalous: boolean;
  risk_score: number;
  anomalies_detected: string[];
  recommendations: string[];
  analyzed_at: string;
}

export interface InvestigationReport {
  id: string;
  tenant_id: string;
  payment_intent_id: string;
  title: string;
  findings: string[];
  status: string;
  replay_result?: ReplayResult | null;
  created_at: string;
}

export interface InvestigationListResponse {
  total: number;
  items: InvestigationReport[];
}

export interface DisputeOSEvidenceBundle {
  case_id?: string;
  payment_intent_id: string;
  evidence_records: EvidenceRecord[];
  timeline: ReplayTimelineEntry[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// DisputeOS Models
// ---------------------------------------------------------------------------

export interface DisputeEvidenceCitation {
  claim: string;
  evidence_id: string;
  verbatim_excerpt: string;
  verified: boolean;
}

export interface DisputeCase {
  id: string;
  tenant_id: string;
  correlation_id: string;
  payment_intent_id: string;
  paypal_dispute_id?: string | null;
  source_type: DisputeSourceType;
  is_synthetic: boolean;
  reason: string;
  buyer_claim: string;
  amount_minor: number;
  currency: string;
  status: DisputeStatus;
  evidence_ids: string[];
  human_approved_for_submission: boolean;
  approved_by?: string | null;
  approved_at?: string | null;
  response_payload_hash?: string | null;
  opened_at: string;
  updated_at: string;
  schema_version?: string;
}

export interface DisputeAnalysis {
  id: string;
  tenant_id: string;
  correlation_id: string;
  dispute_case_id: string;
  is_synthetic: boolean;
  recommendation: DisputeRecommendation;
  confidence_score: number;
  agent_authorized: boolean;
  agent_followed_policy: boolean;
  merchant_fulfilled_order?: boolean | null;
  contradictions: string[];
  missing_evidence: string[];
  citations: DisputeEvidenceCitation[];
  rejected_claims: string[];
  grounded_summary: string;
  draft_response_text: string;
  requires_human_approval: boolean;
  generated_with_llm: boolean;
  analyzed_at: string;
  schema_version?: string;
}

export interface DisputeReport {
  case_id: string;
  case_summary: DisputeCase;
  analysis?: DisputeAnalysis | null;
  evidence_graph?: Record<string, unknown>;
  timeline?: ReplayTimelineEntry[];
  generated_at: string;
}

export interface DisputeCaseDetailResponse {
  case: DisputeCase;
  analysis?: DisputeAnalysis | null;
  evidence: EvidenceRecord[];
  timeline: ReplayTimelineEntry[];
  report?: DisputeReport | null;
}

export interface AttachEvidenceResponse {
  evidence_id: string;
  case_id: string;
  content_hash: string;
  created_at: string;
}

export interface SubmitDisputeResponse {
  case_id: string;
  status: DisputeStatus;
  submitted_at: string;
  paypal_response?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Settings, Webhooks, Outbox / DLQ Models
// ---------------------------------------------------------------------------

export interface WebhookEndpoint {
  id: string;
  url: string;
  description: string;
  event_types: string[];
  status: string;
  created_at: string;
  signing_secret?: string; // returned upon creation
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  event_id: string;
  event_type: string;
  status: "DELIVERED" | "FAILED" | "PENDING";
  response_status?: number | null;
  error_message?: string | null;
  delivered_at?: string | null;
  created_at: string;
}

export interface OutboxEvent {
  id: string;
  tenant_id: string;
  aggregate_type: string;
  aggregate_id: string;
  event_type: string;
  status: "PENDING" | "PROCESSING" | "DELIVERED" | "DEAD_LETTER";
  retry_count: number;
  max_retries: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Request Payloads
// ---------------------------------------------------------------------------

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
  quote_expires_in_seconds?: number;
  tenant_id?: string;
}

export interface HumanApprovalOptions {
  approver_id?: string;
  approved?: boolean;
  comment?: string;
}

export interface CreateAgentInput {
  name: string;
  purpose?: string;
  framework?: string;
  public_fingerprint: string;
}

export interface CreateMerchantInput {
  name: string;
  domain: string;
  category?: string;
  paypal_merchant_id?: string | null;
  is_allowlisted?: boolean;
  is_sandbox_verified?: boolean;
}

export interface CreatePassportInput {
  agent_id: string;
  policy_version?: string;
  currency?: string;
  total_budget_minor: number;
  per_tx_limit_minor: number;
  daily_limit_minor: number;
  human_approval_threshold_minor?: number;
  allowed_merchant_ids?: string[];
  allowed_categories?: string[];
  allow_unknown_merchants?: boolean;
  expires_in_days?: number;
}

export interface UpdatePassportInput {
  per_tx_limit_minor?: number;
  daily_limit_minor?: number;
  human_approval_threshold_minor?: number;
  allowed_merchant_ids?: string[];
  allowed_categories?: string[];
  allow_unknown_merchants?: boolean;
}

export interface CreateDisputeCaseInput {
  reason: string;
  buyer_claim: string;
  amount_minor: number;
  currency?: string;
  payment_intent_id?: string;
  correlation_id?: string;
  paypal_dispute_id?: string | null;
  source_type?: DisputeSourceType;
  is_synthetic?: boolean;
}

export interface AttachEvidenceInput {
  source_type: EvidenceSourceType;
  source_ref: string;
  title: string;
  content: Record<string, unknown>;
  payment_intent_id?: string;
  correlation_id?: string;
  is_synthetic?: boolean;
}

export interface CreateWebhookEndpointInput {
  url: string;
  description?: string;
  event_types?: string[];
}
