import { describe, expect, it } from "vitest";
import { AegisClient } from "../src/client.js";
import { AegisApprovalRequiredError, AegisPolicyViolationError } from "../src/errors.js";
import {
  createAegisToolInterceptor,
  wrapAegisPurchasingTool,
} from "../src/integrations/vercel-ai.js";

describe("Vercel AI SDK Spending Governance Middleware", () => {
  it("allows tool execution when AEGIS policy outcome is ALLOW", async () => {
    let executedTool = false;

    const mockFetch = async () => {
      return new Response(
        JSON.stringify({
          payment_intent: { id: "pi-allowed-1", state: "CHECKOUT_READY" },
          decision: { outcome: "ALLOW", reason_codes: ["OK_WITHIN_POLICY"], violated_constraints: [] },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      );
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const purchaseTool = wrapAegisPurchasingTool({
      client,
      agentId: "agent-001",
      passportId: "passport-001",
      execute: async (args: { amount_minor: number; item: string }, ctx) => {
        executedTool = true;
        expect(ctx.paymentIntent.id).toBe("pi-allowed-1");
        return { success: true, item: args.item };
      },
    });

    const result = await purchaseTool({ amount_minor: 1200, item: "Compute Units" });
    expect(executedTool).toBe(true);
    expect(result).toEqual({ success: true, item: "Compute Units" });
  });

  it("blocks tool execution and throws AegisPolicyViolationError when outcome is DENY", async () => {
    let executedTool = false;

    const mockFetch = async () => {
      return new Response(
        JSON.stringify({
          payment_intent: { id: "pi-denied-1", state: "FAILED" },
          decision: {
            outcome: "DENY",
            reason_codes: ["DENIED_EXCEEDS_PER_TX_LIMIT"],
            violated_constraints: ["amount_minor > 5000"],
            explanation: "Proposal exceeds per-transaction limit of 5000",
          },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      );
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const purchaseTool = wrapAegisPurchasingTool({
      client,
      agentId: "agent-001",
      passportId: "passport-001",
      execute: async () => {
        executedTool = true;
        return { success: true };
      },
    });

    await expect(
      purchaseTool({ amount_minor: 99000, item: "High End Server" })
    ).rejects.toThrow(AegisPolicyViolationError);

    expect(executedTool).toBe(false);
  });

  it("returns rejection structure when denyMode is return_rejection", async () => {
    let executedTool = false;

    const mockFetch = async () => {
      return new Response(
        JSON.stringify({
          payment_intent: { id: "pi-denied-2", state: "FAILED" },
          decision: {
            outcome: "DENY",
            reason_codes: ["DENIED_MERCHANT_NOT_ALLOWLISTED"],
            violated_constraints: ["merchant not allowlisted"],
            explanation: "Merchant is unapproved",
          },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      );
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const purchaseTool = wrapAegisPurchasingTool({
      client,
      agentId: "agent-001",
      passportId: "passport-001",
      denyMode: "return_rejection",
      execute: async () => {
        executedTool = true;
        return { success: true };
      },
    });

    const res = await purchaseTool({ amount_minor: 500, merchant_name: "Untrusted Store" });
    expect(executedTool).toBe(false);
    expect(res).toEqual({
      executed: false,
      payment_intent_id: "pi-denied-2",
      status: "DENIED",
      decision: expect.any(Object),
      rejection: {
        reason_codes: ["DENIED_MERCHANT_NOT_ALLOWLISTED"],
        violated_constraints: ["merchant not allowlisted"],
        explanation: "Merchant is unapproved",
      },
    });
  });

  it("throws AegisApprovalRequiredError on ESCALATE when approvalMode is throw", async () => {
    let executedTool = false;

    const mockFetch = async () => {
      return new Response(
        JSON.stringify({
          payment_intent: { id: "pi-escalated-1", state: "AWAITING_APPROVAL" },
          decision: {
            outcome: "ESCALATE",
            reason_codes: ["ESCALATED_REQUIRES_HUMAN_APPROVAL"],
            explanation: "Requires manual human approval",
          },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      );
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const purchaseTool = wrapAegisPurchasingTool({
      client,
      agentId: "agent-001",
      passportId: "passport-001",
      approvalMode: "throw",
      execute: async () => {
        executedTool = true;
        return { success: true };
      },
    });

    await expect(
      purchaseTool({ amount_minor: 6000, item: "Server Upgrade" })
    ).rejects.toThrow(AegisApprovalRequiredError);

    expect(executedTool).toBe(false);
  });

  it("polls for approval when approvalMode is poll and proceeds when approved", async () => {
    let callCount = 0;
    const mockFetch = async (url: RequestInfo | URL) => {
      const u = String(url);
      if (u.includes("/proposals")) {
        return new Response(
          JSON.stringify({
            payment_intent: { id: "pi-poll-1", state: "AWAITING_APPROVAL" },
            decision: { outcome: "ESCALATE", reason_codes: ["ESCALATED_REQUIRES_HUMAN_APPROVAL"] },
          }),
          { status: 201, headers: { "Content-Type": "application/json" } }
        );
      }
      if (u.includes("/payments/pi-poll-1")) {
        callCount++;
        // On 2nd poll, transition to CHECKOUT_READY
        const state = callCount >= 2 ? "CHECKOUT_READY" : "AWAITING_APPROVAL";
        return new Response(
          JSON.stringify({ id: "pi-poll-1", state }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("{}", { status: 200 });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    let toolExecuted = false;
    const purchaseTool = wrapAegisPurchasingTool({
      client,
      agentId: "agent-001",
      passportId: "passport-001",
      approvalMode: "poll",
      pollIntervalMs: 10,
      pollTimeoutMs: 1000,
      execute: async () => {
        toolExecuted = true;
        return { status: "ORDER_PLACED" };
      },
    });

    const res = await purchaseTool({ amount_minor: 7500, item: "Batch Compute" });
    expect(callCount).toBeGreaterThanOrEqual(2);
    expect(toolExecuted).toBe(true);
    expect(res).toEqual({ status: "ORDER_PLACED" });
  });

  it("intercepts tool calls in agentic loop via createAegisToolInterceptor", async () => {
    const mockFetch = async () => {
      return new Response(
        JSON.stringify({
          payment_intent: { id: "pi-int-1", state: "CHECKOUT_READY" },
          decision: { outcome: "ALLOW", reason_codes: ["OK_WITHIN_POLICY"] },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      );
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const interceptor = createAegisToolInterceptor(client, "agent-1", "passport-1");

    // Non-purchasing tool: allowed immediately without proposal
    const nonPurchase = await interceptor("search_web", { query: "best GPU prices" });
    expect(nonPurchase.allowed).toBe(true);
    expect(nonPurchase.proposal).toBeUndefined();

    // Purchasing tool: triggers proposal submission
    const purchase = await interceptor("buy_compute_credits", {
      amount_minor: 2500,
      merchant_name: "Cloud Provider",
    });
    expect(purchase.allowed).toBe(true);
    expect(purchase.proposal?.payment_intent.id).toBe("pi-int-1");
  });
});
