import { describe, expect, it } from "vitest";
import { AegisClient } from "../src/client.js";
import { AegisAPIError, AegisTimeoutError } from "../src/errors.js";

describe("AegisClient HTTP Engine & API Coverage", () => {
  it("sends Bearer token, Org ID, and Correlation ID headers", async () => {
    let capturedHeaders: HeadersInit | undefined;
    let capturedUrl = "";

    const mockFetch = async (url: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(url);
      capturedHeaders = init?.headers;
      return new Response(JSON.stringify({ status: "ok", service: "aegis-api" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      bearerToken: "jwt-test-token-123",
      organizationId: "org-uuid-999",
      fetchImpl: mockFetch as typeof fetch,
    });

    const res = await client.health();
    expect(res.status).toBe("ok");
    expect(capturedUrl).toBe("https://aegis.test.local/health");

    const headers = capturedHeaders as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-test-token-123");
    expect(headers["X-Org-Id"]).toBe("org-uuid-999");
    expect(headers["X-Correlation-Id"]).toBeDefined();
  });

  it("sends API Key header when configured", async () => {
    let capturedHeaders: Record<string, string> = {};

    const mockFetch = async (_url: RequestInfo | URL, init?: RequestInit) => {
      capturedHeaders = (init?.headers ?? {}) as Record<string, string>;
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      apiKey: "ak_live_abcdef123456",
      fetchImpl: mockFetch as typeof fetch,
    });

    await client.listAgents();
    expect(capturedHeaders["X-API-Key"]).toBe("ak_live_abcdef123456");
  });

  it("handles AbortController timeouts and throws AegisTimeoutError", async () => {
    const mockFetch = async (_url: RequestInfo | URL, init?: RequestInit) => {
      return new Promise<Response>((_, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      timeoutMs: 50,
      maxRetries: 0,
      fetchImpl: mockFetch as typeof fetch,
    });

    await expect(client.getOverviewMetrics()).rejects.toThrow(AegisTimeoutError);
  });

  it("automatically retries transient 500 errors and succeeds when backend recovers", async () => {
    let attempts = 0;
    const mockFetch = async () => {
      attempts++;
      if (attempts < 3) {
        return new Response(JSON.stringify({ detail: "Database connection failed" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ id: "agent-1", name: "Purchaser" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      maxRetries: 3,
      retryDelayMs: 10,
      fetchImpl: mockFetch as typeof fetch,
    });

    const agent = await client.createAgent({
      name: "Purchaser",
      public_fingerprint: "fingerprint-12345",
    });

    expect(attempts).toBe(3);
    expect(agent.name).toBe("Purchaser");
  });

  it("does NOT retry 4xx client errors", async () => {
    let attempts = 0;
    const mockFetch = async () => {
      attempts++;
      return new Response(
        JSON.stringify({
          error_code: "PERMISSION_DENIED",
          message: "Operation not permitted",
        }),
        { status: 403, headers: { "Content-Type": "application/json" } }
      );
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      maxRetries: 3,
      retryDelayMs: 10,
      fetchImpl: mockFetch as typeof fetch,
    });

    await expect(client.deleteWebhookEndpoint("wh-123")).rejects.toThrow(AegisAPIError);
    expect(attempts).toBe(1);
  });

  it("paginates async iterators across multiple pages", async () => {
    const pages: Record<number, Array<{ id: string; amount_minor: number }>> = {
      0: [
        { id: "tx-1", amount_minor: 100 },
        { id: "tx-2", amount_minor: 200 },
      ],
      2: [
        { id: "tx-3", amount_minor: 300 },
        { id: "tx-4", amount_minor: 400 },
      ],
      4: [],
    };

    const mockFetch = async (url: RequestInfo | URL) => {
      const u = new URL(String(url));
      const offset = parseInt(u.searchParams.get("offset") ?? "0", 10);
      const items = pages[offset] ?? [];
      return new Response(JSON.stringify(items), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const collected: string[] = [];
    for await (const payment of client.listPaymentsIterator({ maxItems: 3, pageSize: 2 })) {
      collected.push(payment.id);
    }

    expect(collected).toEqual(["tx-1", "tx-2", "tx-3"]);
  });

  it("supports Guardian purchase proposals and approval options", async () => {
    let proposalBody: Record<string, unknown> = {};
    let approveBody: Record<string, unknown> = {};

    const mockFetch = async (url: RequestInfo | URL, init?: RequestInit) => {
      const u = String(url);
      if (u.includes("/guardian/proposals") && !u.includes("/approve")) {
        proposalBody = JSON.parse(String(init?.body));
        return new Response(
          JSON.stringify({
            payment_intent: { id: "intent-001", state: "AWAITING_APPROVAL" },
            decision: { outcome: "ESCALATE", reason_codes: ["ESCALATED_REQUIRES_HUMAN_APPROVAL"] },
          }),
          { status: 201, headers: { "Content-Type": "application/json" } }
        );
      }
      if (u.includes("/approve")) {
        approveBody = JSON.parse(String(init?.body));
        return new Response(
          JSON.stringify({
            payment_intent: { id: "intent-001", state: "CHECKOUT_READY" },
            approval: { id: "app-1", approver_id: "human@example.com", status: "APPROVED" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("{}", { status: 200 });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const proposal = await client.submitPurchaseProposal({
      agent_id: "agent-1",
      passport_id: "passport-1",
      merchant_id: "merchant-1",
      merchant_name: "API Provider Inc",
      amount_minor: 4500,
      item_summary: "Monthly Subscription",
      rationale: "Required for LLM inference",
    });

    expect(proposal.payment_intent.id).toBe("intent-001");
    expect(proposalBody.amount_minor).toBe(4500);
    expect(proposalBody.currency).toBe("USD");
    expect(proposalBody.idempotency_key).toBeDefined();

    const approval = await client.approveProposal("intent-001", {
      approver_id: "human@example.com",
      approved: true,
      comment: "Verified expenditure against budget",
    });

    expect(approval.payment_intent.state).toBe("CHECKOUT_READY");
    expect(approveBody.approved).toBe(true);
    expect(approveBody.approver_id).toBe("human@example.com");
  });

  it("supports DisputeOS case management and AI analysis", async () => {
    const mockFetch = async (url: RequestInfo | URL) => {
      const u = String(url);
      if (u.includes("/disputeos/cases/seed-demo")) {
        return new Response(
          JSON.stringify({
            case: { id: "case-001", status: "OPEN", amount_minor: 9900 },
            evidence: [],
            timeline: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (u.includes("/disputeos/cases/case-001/analyze")) {
        return new Response(
          JSON.stringify({
            case: { id: "case-001", status: "UNDER_INVESTIGATION" },
            analysis: {
              recommendation: "CHALLENGE_WITH_EVIDENCE",
              confidence_score: 0.94,
              grounded_summary: "Merchant fulfilled order with proof of carrier tracking.",
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("{}", { status: 200 });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const demo = await client.seedDemoDispute("physical_goods");
    expect(demo.case.id).toBe("case-001");

    const analyzed = await client.analyzeDispute("case-001");
    expect(analyzed.analysis?.recommendation).toBe("CHALLENGE_WITH_EVIDENCE");
    expect(analyzed.analysis?.confidence_score).toBe(0.94);
  });

  it("supports GhostPay simulations and forensic replay", async () => {
    let simulationBody: Record<string, unknown> = {};

    const mockFetch = async (url: RequestInfo | URL, init?: RequestInit) => {
      simulationBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          replay_id: "rep-101",
          consistency_status: "CONSISTENT",
          original_outcome: "ALLOW",
          recomputed_outcome: "DENY",
          drift_detected: true,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const sim = await client.simulateByPayment(
      "intent-999",
      { per_tx_limit_minor: 2500 },
      true,
      "policy-v2"
    );

    expect(sim.drift_detected).toBe(true);
    expect(sim.recomputed_outcome).toBe("DENY");
    expect(simulationBody.policy_version).toBe("policy-v2");
    expect(simulationBody.persist_investigation).toBe(true);
  });

  it("supports Webhook & DLQ Outbox management", async () => {
    const mockFetch = async (url: RequestInfo | URL) => {
      const u = String(url);
      if (u.includes("/worker/outbox/outbox-1/requeue")) {
        return new Response(
          JSON.stringify({ id: "outbox-1", status: "PENDING", retry_count: 0 }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    };

    const client = new AegisClient({
      baseUrl: "https://aegis.test.local",
      fetchImpl: mockFetch as typeof fetch,
    });

    const requeued = await client.requeueOutboxEvent("outbox-1");
    expect(requeued.id).toBe("outbox-1");
    expect(requeued.status).toBe("PENDING");
  });
});
