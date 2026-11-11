"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type AgentRecord, type MerchantRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, truncateId } from "@/lib/format";

export default function AgentsMerchantsPage() {
  const { session, hasPermission } = useAuth();
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [merchants, setMerchants] = useState<MerchantRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [agentName, setAgentName] = useState("");
  const [agentPurpose, setAgentPurpose] = useState("Cloud procurement");
  const [agentFramework, setAgentFramework] = useState("langgraph");
  const [fingerprint, setFingerprint] = useState("");

  const [merchantName, setMerchantName] = useState("");
  const [merchantDomain, setMerchantDomain] = useState("");
  const [merchantCategory, setMerchantCategory] = useState("SOFTWARE");
  const [confirmSuspend, setConfirmSuspend] = useState<AgentRecord | null>(null);

  const loadData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const [a, m] = await Promise.all([
        apiRequest<AgentRecord[]>("/v1/guardian/agents", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<MerchantRecord[]>("/v1/guardian/merchants", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
      ]);
      setAgents(a);
      setMerchants(m);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agents and merchants");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleCreateAgent(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError(null);
    try {
      await apiRequest("/v1/guardian/agents", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          name: agentName.trim(),
          purpose: agentPurpose.trim(),
          framework: agentFramework,
          public_fingerprint: fingerprint.trim() || `fp-${crypto.randomUUID().slice(0, 12)}`,
        },
      });
      setAgentName("");
      setFingerprint("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register agent");
    }
  }

  async function handleToggleAgentStatus(agent: AgentRecord, nextStatus: "ACTIVE" | "SUSPENDED") {
    if (!session) return;
    setError(null);
    try {
      await apiRequest(`/v1/guardian/agents/${agent.id}/status`, {
        method: "PATCH",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { status: nextStatus },
      });
      setConfirmSuspend(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update agent status");
    }
  }

  async function handleCreateMerchant(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError(null);
    try {
      await apiRequest("/v1/guardian/merchants", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          name: merchantName.trim(),
          domain: merchantDomain.trim(),
          category: merchantCategory.trim().toUpperCase(),
          is_allowlisted: true,
          is_sandbox_verified: true,
        },
      });
      setMerchantName("");
      setMerchantDomain("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create merchant");
    }
  }

  async function handleToggleMerchantAllowlist(merchant: MerchantRecord) {
    if (!session) return;
    try {
      await apiRequest(`/v1/guardian/merchants/${merchant.id}/allowlist`, {
        method: "PATCH",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { is_allowlisted: !merchant.is_allowlisted },
      });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update allowlist");
    }
  }

  return (
    <AppShell title="Agents & Merchants" subtitle="Register AI identities, control agent states, and manage merchant allowlists">
      {error && (
        <div role="status" className="mb-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {hasPermission("agents:write") && (
          <form onSubmit={(e) => void handleCreateAgent(e)} className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <h2 className="text-base font-semibold text-white">Register AI Agent</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="agent-name" className="block text-xs font-medium text-slate-300">
                  Agent Name *
                </label>
                <input
                  id="agent-name"
                  required
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="Procurement-Bot"
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label htmlFor="agent-framework" className="block text-xs font-medium text-slate-300">
                  Framework
                </label>
                <select
                  id="agent-framework"
                  value={agentFramework}
                  onChange={(e) => setAgentFramework(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                >
                  <option value="langgraph">LangGraph</option>
                  <option value="pydantic-ai">PydanticAI</option>
                  <option value="custom">Custom Python / TS SDK</option>
                </select>
              </div>
              <div>
                <label htmlFor="agent-purpose" className="block text-xs font-medium text-slate-300">
                  Purpose
                </label>
                <input
                  id="agent-purpose"
                  value={agentPurpose}
                  onChange={(e) => setAgentPurpose(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label htmlFor="agent-fp" className="block text-xs font-medium text-slate-300">
                  Public Key Fingerprint (optional)
                </label>
                <input
                  id="agent-fp"
                  value={fingerprint}
                  onChange={(e) => setFingerprint(e.target.value)}
                  placeholder="Auto-generated if empty"
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>
            </div>
            <button type="submit" className="mt-4 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400">
              Register Agent
            </button>
          </form>
        )}

        {hasPermission("merchants:write") && (
          <form onSubmit={(e) => void handleCreateMerchant(e)} className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <h2 className="text-base font-semibold text-white">Add Allowlisted Merchant</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="m-name" className="block text-xs font-medium text-slate-300">
                  Merchant Name *
                </label>
                <input
                  id="m-name"
                  required
                  value={merchantName}
                  onChange={(e) => setMerchantName(e.target.value)}
                  placeholder="CloudDocs Pro"
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label htmlFor="m-domain" className="block text-xs font-medium text-slate-300">
                  Domain *
                </label>
                <input
                  id="m-domain"
                  required
                  value={merchantDomain}
                  onChange={(e) => setMerchantDomain(e.target.value)}
                  placeholder="clouddocs.example.com"
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label htmlFor="m-cat" className="block text-xs font-medium text-slate-300">
                  Category
                </label>
                <input
                  id="m-cat"
                  value={merchantCategory}
                  onChange={(e) => setMerchantCategory(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>
            </div>
            <button type="submit" className="mt-4 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400">
              Add Merchant
            </button>
          </form>
        )}
      </div>

      <section className="mt-8">
        <h2 id="agents-caption" className="mb-3 text-base font-semibold text-white">
          Registered Agents ({agents.length})
        </h2>
        <div tabIndex={0} role="region" aria-labelledby="agents-caption" className="table-wrapper">
          <table className="aegis-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Framework</th>
                <th scope="col">Status</th>
                <th scope="col">Fingerprint</th>
                <th scope="col">Created</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && agents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400">
                    Loading agents…
                  </td>
                </tr>
              ) : agents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400">
                    No AI agents registered yet.
                  </td>
                </tr>
              ) : (
                agents.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <div className="font-medium text-white">{a.name}</div>
                      <div className="font-mono text-xs text-slate-400">{a.id}</div>
                    </td>
                    <td className="text-slate-300">{a.framework}</td>
                    <td>
                      <StatusBadge label={a.status} />
                    </td>
                    <td className="font-mono text-xs text-slate-400">{truncateId(a.public_fingerprint, 16)}</td>
                    <td className="text-xs text-slate-400">{formatIsoDateTime(a.created_at)}</td>
                    <td>
                      {hasPermission("agents:write") && (
                        a.status === "ACTIVE" ? (
                          <button
                            type="button"
                            onClick={() => setConfirmSuspend(a)}
                            className="rounded border border-rose-500/40 px-2.5 py-1 text-xs text-rose-300 hover:bg-rose-500/15"
                          >
                            Suspend
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => void handleToggleAgentStatus(a, "ACTIVE")}
                            className="rounded border border-emerald-500/40 px-2.5 py-1 text-xs text-emerald-300 hover:bg-emerald-500/15"
                          >
                            Activate
                          </button>
                        )
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8">
        <h2 id="merchants-caption" className="mb-3 text-base font-semibold text-white">
          Merchants ({merchants.length})
        </h2>
        <div tabIndex={0} role="region" aria-labelledby="merchants-caption" className="table-wrapper">
          <table className="aegis-table">
            <thead>
              <tr>
                <th scope="col">Merchant</th>
                <th scope="col">Domain</th>
                <th scope="col">Category</th>
                <th scope="col">Allowlisted</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {merchants.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-slate-400">
                    No merchants configured yet.
                  </td>
                </tr>
              ) : (
                merchants.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <div className="font-medium text-white">{m.name}</div>
                      <div className="font-mono text-xs text-slate-400">{m.id}</div>
                    </td>
                    <td className="text-slate-300">{m.domain}</td>
                    <td className="text-slate-300">{m.category}</td>
                    <td>
                      <StatusBadge label={m.is_allowlisted ? "ACTIVE" : "SUSPENDED"} />
                    </td>
                    <td>
                      {hasPermission("merchants:write") && (
                        <button
                          type="button"
                          onClick={() => void handleToggleMerchantAllowlist(m)}
                          className="rounded border border-aegis-border px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
                        >
                          {m.is_allowlisted ? "Remove Allowlist" : "Allowlist"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmDialog
        open={Boolean(confirmSuspend)}
        title="Suspend AI Agent"
        description={`Suspending "${confirmSuspend?.name ?? ""}" immediately prevents it from submitting new purchase proposals.`}
        confirmLabel="Suspend Agent"
        destructive
        onCancel={() => setConfirmSuspend(null)}
        onConfirm={() => {
          if (confirmSuspend) void handleToggleAgentStatus(confirmSuspend, "SUSPENDED");
        }}
      />
    </AppShell>
  );
}
