"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
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

  // Search & Pagination states
  const [agentSearch, setAgentSearch] = useState("");
  const [agentLimit, setAgentLimit] = useState(10);
  const [agentOffset, setAgentOffset] = useState(0);

  const [merchantSearch, setMerchantSearch] = useState("");
  const [merchantLimit, setMerchantLimit] = useState(10);
  const [merchantOffset, setMerchantOffset] = useState(0);

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
      const agentParams = new URLSearchParams({
        limit: String(agentLimit),
        offset: String(agentOffset),
      });
      if (agentSearch.trim()) agentParams.set("q", agentSearch.trim());

      const merchantParams = new URLSearchParams({
        limit: String(merchantLimit),
        offset: String(merchantOffset),
      });
      if (merchantSearch.trim()) merchantParams.set("q", merchantSearch.trim());

      const [a, m] = await Promise.all([
        apiRequest<AgentRecord[]>(`/v1/guardian/agents?${agentParams.toString()}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<MerchantRecord[]>(`/v1/guardian/merchants?${merchantParams.toString()}`, {
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
  }, [agentLimit, agentOffset, agentSearch, merchantLimit, merchantOffset, merchantSearch, session]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Client-side search and pagination filtering
  const filteredAgents = useMemo(() => {
    const q = agentSearch.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.id.toLowerCase().includes(q) ||
        a.purpose.toLowerCase().includes(q) ||
        a.framework.toLowerCase().includes(q) ||
        a.public_fingerprint.toLowerCase().includes(q) ||
        a.status.toLowerCase().includes(q),
    );
  }, [agents, agentSearch]);

  const pagedAgents = useMemo(() => {
    return filteredAgents.slice(agentOffset, agentOffset + agentLimit);
  }, [filteredAgents, agentOffset, agentLimit]);

  const filteredMerchants = useMemo(() => {
    const q = merchantSearch.trim().toLowerCase();
    if (!q) return merchants;
    return merchants.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        m.domain.toLowerCase().includes(q) ||
        m.category.toLowerCase().includes(q),
    );
  }, [merchants, merchantSearch]);

  const pagedMerchants = useMemo(() => {
    return filteredMerchants.slice(merchantOffset, merchantOffset + merchantLimit);
  }, [filteredMerchants, merchantOffset, merchantLimit]);

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

        {/* GAP-004: Fix permission check from "merchants:write" to "passports:write" */}
        {hasPermission("passports:write") && (
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

      {/* Agents Table with Search & Pagination */}
      <section className="mt-8 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
          <h2 id="agents-caption" className="text-base font-semibold text-white">
            Registered Agents ({filteredAgents.length})
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <input
                type="text"
                value={agentSearch}
                onChange={(e) => {
                  setAgentSearch(e.target.value);
                  setAgentOffset(0);
                }}
                placeholder="Search agents (name, purpose, framework)..."
                className="w-64 rounded-lg border border-aegis-border bg-aegis-bg px-3 py-1.5 text-xs text-white placeholder-slate-400"
              />
              {agentSearch && (
                <button
                  type="button"
                  onClick={() => {
                    setAgentSearch("");
                    setAgentOffset(0);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              )}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-slate-300">
              <label htmlFor="agent-limit-select">Limit:</label>
              <select
                id="agent-limit-select"
                value={agentLimit}
                onChange={(e) => {
                  setAgentLimit(Number(e.target.value));
                  setAgentOffset(0);
                }}
                className="rounded border border-aegis-border bg-aegis-bg px-2 py-1 text-xs text-white"
              >
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
            </div>
          </div>
        </div>

        <div tabIndex={0} role="region" aria-labelledby="agents-caption" className="table-wrapper">
          <table className="aegis-table w-full text-left text-sm">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Framework</th>
                <th scope="col">Status</th>
                <th scope="col">Fingerprint</th>
                <th scope="col">Created</th>
                <th scope="col" className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && agents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400 py-6">
                    Loading agents…
                  </td>
                </tr>
              ) : pagedAgents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400 py-6">
                    {agentSearch ? "No agents matching your search." : "No AI agents registered yet."}
                  </td>
                </tr>
              ) : (
                pagedAgents.map((a) => (
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
                    <td className="text-right">
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

        {/* Agents Pagination Bar */}
        {filteredAgents.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 text-xs text-slate-400">
            <div>
              Showing {Math.min(filteredAgents.length, agentOffset + 1)} to {Math.min(filteredAgents.length, agentOffset + agentLimit)} of {filteredAgents.length} agents
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={agentOffset === 0}
                onClick={() => setAgentOffset((prev) => Math.max(0, prev - agentLimit))}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Previous
              </button>
              <span>
                Page {Math.floor(agentOffset / agentLimit) + 1} of {Math.max(1, Math.ceil(filteredAgents.length / agentLimit))}
              </span>
              <button
                type="button"
                disabled={agentOffset + agentLimit >= filteredAgents.length}
                onClick={() => setAgentOffset((prev) => prev + agentLimit)}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Merchants Table with Search & Pagination */}
      <section className="mt-8 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
          <h2 id="merchants-caption" className="text-base font-semibold text-white">
            Merchants ({filteredMerchants.length})
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <input
                type="text"
                value={merchantSearch}
                onChange={(e) => {
                  setMerchantSearch(e.target.value);
                  setMerchantOffset(0);
                }}
                placeholder="Search merchants (name, domain, category)..."
                className="w-64 rounded-lg border border-aegis-border bg-aegis-bg px-3 py-1.5 text-xs text-white placeholder-slate-400"
              />
              {merchantSearch && (
                <button
                  type="button"
                  onClick={() => {
                    setMerchantSearch("");
                    setMerchantOffset(0);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              )}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-slate-300">
              <label htmlFor="merchant-limit-select">Limit:</label>
              <select
                id="merchant-limit-select"
                value={merchantLimit}
                onChange={(e) => {
                  setMerchantLimit(Number(e.target.value));
                  setMerchantOffset(0);
                }}
                className="rounded border border-aegis-border bg-aegis-bg px-2 py-1 text-xs text-white"
              >
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
            </div>
          </div>
        </div>

        <div tabIndex={0} role="region" aria-labelledby="merchants-caption" className="table-wrapper">
          <table className="aegis-table w-full text-left text-sm">
            <thead>
              <tr>
                <th scope="col">Merchant</th>
                <th scope="col">Domain</th>
                <th scope="col">Category</th>
                <th scope="col">Allowlisted</th>
                <th scope="col" className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && merchants.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-slate-400 py-6">
                    Loading merchants…
                  </td>
                </tr>
              ) : pagedMerchants.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-slate-400 py-6">
                    {merchantSearch ? "No merchants matching your search." : "No merchants configured yet."}
                  </td>
                </tr>
              ) : (
                pagedMerchants.map((m) => (
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
                    <td className="text-right">
                      {/* GAP-004: Fix permission check from "merchants:write" to "passports:write" */}
                      {hasPermission("passports:write") && (
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

        {/* Merchants Pagination Bar */}
        {filteredMerchants.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 text-xs text-slate-400">
            <div>
              Showing {Math.min(filteredMerchants.length, merchantOffset + 1)} to {Math.min(filteredMerchants.length, merchantOffset + merchantLimit)} of {filteredMerchants.length} merchants
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={merchantOffset === 0}
                onClick={() => setMerchantOffset((prev) => Math.max(0, prev - merchantLimit))}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Previous
              </button>
              <span>
                Page {Math.floor(merchantOffset / merchantLimit) + 1} of {Math.max(1, Math.ceil(filteredMerchants.length / merchantLimit))}
              </span>
              <button
                type="button"
                disabled={merchantOffset + merchantLimit >= filteredMerchants.length}
                onClick={() => setMerchantOffset((prev) => prev + merchantLimit)}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
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
