/**
 * Vercel AI SDK Spending Governance Middleware & Tool Interceptor for AEGIS.
 * Intercepts tool calls and proposals before model execution, deterministically
 * enforcing spending limits, passports, merchant allowlists, and human approval gates.
 */

import type { AegisClient } from "../client.js";
import { AegisApprovalRequiredError, AegisPolicyViolationError } from "../errors.js";
import type {
  AuthorizationDecision,
  PaymentIntent,
  ProposalSubmissionResponse,
  SubmitProposalInput,
} from "../types.js";

export interface ProposalExtractionContext<TArgs = unknown> {
  toolCallId?: string;
  args: TArgs;
}

export type ProposalExtractor<TArgs = unknown> = (
  ctx: ProposalExtractionContext<TArgs>
) => Omit<SubmitProposalInput, "agent_id" | "passport_id"> & {
  agent_id?: string;
  passport_id?: string;
};

export interface WrapAegisToolOptions<TArgs = unknown, TResult = unknown> {
  client: AegisClient;
  agentId: string;
  passportId: string;
  merchantId?: string;
  /**
   * Optional custom extractor to map tool arguments to a PurchaseProposal.
   * If omitted, attempts to map standard field names from args.
   */
  extractProposal?: ProposalExtractor<TArgs>;
  /**
   * Action when a proposal is ESCALATED (requires human approval).
   * - "throw": Throws AegisApprovalRequiredError with intent ID.
   * - "poll": Polls until approved or rejected (up to maxWaitMs).
   * - "return_status": Returns a structured object indicating approval is pending without executing the tool.
   * Default is "throw".
   */
  approvalMode?: "throw" | "poll" | "return_status";
  /**
   * Maximum wait time when approvalMode is "poll" in milliseconds (default 60000 = 1m).
   */
  pollTimeoutMs?: number;
  /**
   * Polling interval in milliseconds (default 2000 = 2s).
   */
  pollIntervalMs?: number;
  /**
   * Action when a proposal is DENIED.
   * - "throw": Throws AegisPolicyViolationError (default).
   * - "return_rejection": Returns structured rejection object to the LLM context.
   */
  denyMode?: "throw" | "return_rejection";
  /**
   * Underlying tool execution function.
   */
  execute: (
    args: TArgs,
    context: {
      toolCallId?: string;
      paymentIntent: PaymentIntent;
      decision: AuthorizationDecision;
      abortSignal?: AbortSignal;
    }
  ) => Promise<TResult>;
}

export interface GovernedToolResult<TResult = unknown> {
  executed: boolean;
  payment_intent_id: string;
  status: "EXECUTED" | "DENIED" | "AWAITING_APPROVAL";
  result?: TResult;
  decision?: AuthorizationDecision;
  rejection?: {
    reason_codes: string[];
    violated_constraints: string[];
    explanation: string;
  };
}

function defaultExtractProposal(ctxOrArgs: unknown): Omit<SubmitProposalInput, "agent_id" | "passport_id"> {
  if (!ctxOrArgs || typeof ctxOrArgs !== "object") {
    throw new Error("Unable to extract purchase proposal: tool arguments must be an object");
  }

  // Handle either direct arguments or ProposalExtractionContext wrapper { args, toolCallId }
  const record = (
    "args" in ctxOrArgs && ctxOrArgs.args && typeof ctxOrArgs.args === "object"
      ? ctxOrArgs.args
      : ctxOrArgs
  ) as Record<string, unknown>;

  const amountMinor =
    typeof record.amount_minor === "number"
      ? record.amount_minor
      : typeof record.amountMinor === "number"
      ? record.amountMinor
      : typeof record.amount === "number"
      ? Math.round(record.amount * 100)
      : undefined;

  if (amountMinor === undefined || amountMinor <= 0) {
    throw new Error("Unable to extract purchase proposal: missing or non-positive amount_minor in tool arguments");
  }

  const merchantName =
    (record.merchant_name as string) ||
    (record.merchantName as string) ||
    (record.merchant as string) ||
    "Unknown Merchant";

  const merchantId =
    (record.merchant_id as string) ||
    (record.merchantId as string) ||
    "00000000-0000-0000-0000-000000000000";

  const itemSummary =
    (record.item_summary as string) ||
    (record.itemSummary as string) ||
    (record.description as string) ||
    (record.item as string) ||
    "AI Agent Purchase";

  const rationale =
    (record.rationale as string) ||
    (record.reason as string) ||
    (record.justification as string) ||
    `Automated purchase by agent for: ${itemSummary}`;

  return {
    merchant_id: merchantId,
    merchant_name: merchantName,
    merchant_category: (record.merchant_category as string) || (record.category as string) || "SOFTWARE",
    amount_minor: amountMinor,
    currency: ((record.currency as string) || "USD").toUpperCase(),
    item_summary: itemSummary,
    rationale,
    line_items: Array.isArray(record.line_items) ? (record.line_items as Array<Record<string, unknown>>) : [],
    idempotency_key: (record.idempotency_key as string) || `vai-${crypto.randomUUID()}`,
  };
}

/**
 * Wraps a Vercel AI SDK purchasing tool execution function with AEGIS deterministic spending governance.
 */
export function wrapAegisPurchasingTool<TArgs = unknown, TResult = unknown>(
  options: WrapAegisToolOptions<TArgs, TResult>
) {
  const {
    client,
    agentId,
    passportId,
    merchantId,
    extractProposal = defaultExtractProposal,
    approvalMode = "throw",
    pollTimeoutMs = 60000,
    pollIntervalMs = 2000,
    denyMode = "throw",
    execute,
  } = options;

  return async (
    args: TArgs,
    execOptions?: { toolCallId?: string; abortSignal?: AbortSignal }
  ): Promise<TResult | GovernedToolResult<TResult>> => {
    // 1. Extract proposal parameters
    const extracted = extractProposal({
      toolCallId: execOptions?.toolCallId,
      args,
    });

    const proposalInput: SubmitProposalInput = {
      agent_id: ("agent_id" in extracted && typeof extracted.agent_id === "string" ? extracted.agent_id : undefined) || agentId,
      passport_id: ("passport_id" in extracted && typeof extracted.passport_id === "string" ? extracted.passport_id : undefined) || passportId,
      merchant_id: extracted.merchant_id || merchantId || "00000000-0000-0000-0000-000000000000",
      merchant_name: extracted.merchant_name,
      merchant_category: extracted.merchant_category,
      amount_minor: extracted.amount_minor,
      currency: extracted.currency,
      item_summary: extracted.item_summary,
      rationale: extracted.rationale,
      line_items: extracted.line_items,
      idempotency_key: extracted.idempotency_key,
    };

    // 2. Submit proposal to AEGIS Guardian
    const submission: ProposalSubmissionResponse = await client.submitPurchaseProposal(proposalInput);
    const { payment_intent, decision } = submission;

    // 3. Handle Policy DENIAL
    if (decision.outcome === "DENY") {
      if (denyMode === "throw") {
        throw new AegisPolicyViolationError(
          decision.outcome,
          decision.reason_codes,
          decision.violated_constraints,
          decision.explanation
        );
      }
      return {
        executed: false,
        payment_intent_id: payment_intent.id,
        status: "DENIED",
        decision,
        rejection: {
          reason_codes: decision.reason_codes,
          violated_constraints: decision.violated_constraints,
          explanation: decision.explanation,
        },
      };
    }

    // 4. Handle Policy ESCALATION (Human Approval Gate)
    if (decision.outcome === "ESCALATE") {
      if (approvalMode === "throw") {
        throw new AegisApprovalRequiredError(payment_intent.id, decision.explanation);
      }

      if (approvalMode === "return_status") {
        return {
          executed: false,
          payment_intent_id: payment_intent.id,
          status: "AWAITING_APPROVAL",
          decision,
        };
      }

      // Polling mode: wait for human approval in AEGIS Console
      const startTime = Date.now();
      let currentIntent = payment_intent;

      while (Date.now() - startTime < pollTimeoutMs) {
        if (execOptions?.abortSignal?.aborted) {
          throw new DOMException("Aborted while waiting for approval", "AbortError");
        }

        await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
        currentIntent = await client.getPayment(payment_intent.id);

        if (currentIntent.state === "CHECKOUT_READY" || currentIntent.state === "SUCCEEDED") {
          break;
        }

        if (currentIntent.state === "CANCELLED" || currentIntent.state === "FAILED") {
          throw new AegisPolicyViolationError(
            "DENY",
            ["HUMAN_REJECTED" as unknown as typeof decision.reason_codes[0]],
            [],
            "Human approver rejected this spending proposal in AEGIS Console"
          );
        }
      }

      if (currentIntent.state !== "CHECKOUT_READY" && currentIntent.state !== "SUCCEEDED") {
        throw new AegisApprovalRequiredError(
          payment_intent.id,
          `Timed out after ${pollTimeoutMs}ms waiting for human approval`
        );
      }
    }

    // 5. ALLOW outcome -> Execute underlying purchasing logic
    return execute(args, {
      toolCallId: execOptions?.toolCallId,
      paymentIntent: payment_intent,
      decision,
      abortSignal: execOptions?.abortSignal,
    });
  };
}

/**
 * Creates an interceptor for pre-execution tool checks in agentic loops.
 */
export function createAegisToolInterceptor(client: AegisClient, defaultAgentId: string, defaultPassportId: string) {
  return async function interceptToolCall<TArgs = Record<string, unknown>>(
    toolName: string,
    args: TArgs
  ): Promise<{ allowed: boolean; reason?: string; proposal?: ProposalSubmissionResponse }> {
    const isPurchasingTool = /buy|purchase|checkout|pay|order|subscribe|transfer/i.test(toolName);
    if (!isPurchasingTool) {
      return { allowed: true };
    }

    try {
      const extracted = defaultExtractProposal(args);
      const submission = await client.submitPurchaseProposal({
        ...extracted,
        agent_id: defaultAgentId,
        passport_id: defaultPassportId,
      });

      if (submission.decision.outcome === "DENY") {
        return {
          allowed: false,
          reason: `Policy denied: ${submission.decision.reason_codes.join(", ")}`,
          proposal: submission,
        };
      }

      if (submission.decision.outcome === "ESCALATE") {
        return {
          allowed: false,
          reason: `Human approval required: ${submission.decision.explanation}`,
          proposal: submission,
        };
      }

      return { allowed: true, proposal: submission };
    } catch (err) {
      return {
        allowed: false,
        reason: err instanceof Error ? err.message : String(err),
      };
    }
  };
}
