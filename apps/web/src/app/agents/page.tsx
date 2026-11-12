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
    <AppShell title="Agents & Merchants" subtitle="Register AI identities, control agent operational states, and manage category allowlists">
      {error && (
        <div role="status" className="mb-6 rounded-md border border-aegis-rose/40 bg-aegis-rose/10 p-4 text-xs font-mono text-aegis-rose">
          [FAULT] {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {hasPermission("agents:write") && (
          <form onSubmit={(e) => void handleCreateAgent(e)} className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex items-center justify-between border-b border-aegis-border pb-3">
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[IDENTITY // PROVISION]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Register AI Agent</h2>
              </div>
              <span className="font-mono text-[11px] text-aegis-text-muted">TENANT-SCOPED</span>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="agent-name" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Agent Name *
                </label>
                <input
                  id="agent-name"
                  required
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="Procurement-Bot-01"
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="agent-framework" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Framework
                </label>
                <select
                  id="agent-framework"
                  value={agentFramework}
                  onChange={(e) => setAgentFramework(e.target.value)}
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                >
                  <option value="langgraph">LangGraph</option>
                  <option value="pydantic-ai">PydanticAI</option>
                  <option value="custom">Custom Python / TS SDK</option>
                </select>
              </div>
              <div>
                <label htmlFor="agent-purpose" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Purpose / Scope
                </label>
                <input
                  id="agent-purpose"
                  value={agentPurpose}
                  onChange={(e) => setAgentPurpose(e.target.value)}
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="agent-fp" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Fingerprint (optional)
                </label>
                <input
                  id="agent-fp"
                  value={fingerprint}
                  onChange={(e) => setFingerprint(e.target.value)}
                  placeholder="Auto-generated if empty"
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              className="mt-5 rounded bg-aegis-accent px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition"
            >
              Register Agent Identity
            </button>
          </form>
        )}

        {/* GAP-004: Fix permission check from "merchants:write" to "passports:write" */}
        {hasPermission("passports:write") && (
          <form onSubmit={(e) => void handleCreateMerchant(e)} className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex items-center justify-between border-b border-aegis-border pb-3">
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper">[ALLOWLIST // GATEWAY]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Add Allowlisted Merchant</h2>
              </div>
              <span className="font-mono text-[11px] text-aegis-text-muted">MCC VERIFIED</span>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="m-name" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Merchant Name *
                </label>
                <input
                  id="m-name"
                  required
                  value={merchantName}
                  onChange={(e) => setMerchantName(e.target.value)}
                  placeholder="CloudDocs Pro"
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="m-domain" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Domain *
                </label>
                <input
                  id="m-domain"
                  required
                  value={merchantDomain}
                  onChange={(e) => setMerchantDomain(e.target.value)}
                  placeholder="clouddocs.example.com"
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="m-cat" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Category (MCC)
                </label>
                <input
                  id="m-cat"
                  value={merchantCategory}
                  onChange={(e) => setMerchantCategory(e.target.value)}
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs uppercase text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              className="mt-5 rounded border border-aegis-copper/60 bg-aegis-copper/15 px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-aegis-copper hover:bg-aegis-copper/25 transition"
            >
              Add Allowlisted Vendor
            </button>
          </form>
        )}
      </div>

      {/* Agents Table with Search & Pagination */}
      <section className="mt-8 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[ROSTER // ACTIVE AGENTS]</span>
            <h2 id="agents-caption" className="text-sm font-semibold tracking-wide text-aegis-text-primary">
              Registered Autonomous Identities ({filteredAgents.length})
            </h2>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <input
                type="text"
                value={agentSearch}
                onChange={(e) => {
                  setAgentSearch(e.target.value);
                  setAgentOffset(0);
                }}
                placeholder="Filter by name, ID, framework..."
                className="w-64 rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
              {agentSearch && (
                <button
                  type="button"
                  onClick={() => {
                    setAgentSearch("");
                    setAgentOffset(0);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 font-mono text-xs text-aegis-text-muted hover:text-aegis-text-primary"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="flex items-center gap-1.5 font-mono text-xs text-aegis-text-muted">
              <label htmlFor="agent-limit-select">Limit:</label>
              <select
                id="agent-limit-select"
                value={agentLimit}
                onChange={(e) => {
                  setAgentLimit(Number(e.target.value));
                  setAgentOffset(0);
                }}
                className="rounded border border-aegis-border bg-aegis-card px-2 py-1 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
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
          <table className="aegis-table w-full text-left text-xs">
            <thead>
              <tr>
                <th scope="col">Agent Identity</th>
                <th scope="col">Framework</th>
                <th scope="col">Operational State</th>
                <th scope="col">Key Fingerprint</th>
                <th scope="col">Provisioned</th>
                <th scope="col" className="text-right">Controls</th>
              </tr>
            </thead>
            <tbody>
              {loading && agents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-6 text-center font-mono text-aegis-text-muted">
                    Loading agent identities…
                  </td>
                </tr>
              ) : pagedAgents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-6 text-center font-mono text-aegis-text-muted">
                    {agentSearch ? "No agents matching query." : "No AI agent identities registered yet."}
                  </td>
                </tr>
              ) : (
                pagedAgents.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <div className="font-semibold text-aegis-text-primary">{a.name}</div>
                      <div className="font-mono text-[11px] text-aegis-text-faint">{a.id}</div>
                    </td>
                    <td className="font-mono text-aegis-text-muted">{a.framework}</td>
                    <td>
                      <StatusBadge label={a.status} />
                    </td>
                    <td className="font-mono text-[11px] text-aegis-text-muted">{truncateId(a.public_fingerprint, 18)}</td>
                    <td className="font-mono text-[11px] text-aegis-text-faint">{formatIsoDateTime(a.created_at)}</td>
                    <td className="text-right">
                      {hasPermission("agents:write") && (
                        a.status === "ACTIVE" ? (
                          <button
                            type="button"
                            onClick={() => setConfirmSuspend(a)}
                            className="rounded border border-aegis-rose/40 bg-aegis-rose/10 px-2.5 py-1 font-mono text-[11px] text-aegis-rose hover:bg-aegis-rose/20 transition"
                          >
                            Suspend
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => void handleToggleAgentStatus(a, "ACTIVE")}
                            className="rounded border border-aegis-accent/40 bg-aegis-accent/10 px-2.5 py-1 font-mono text-[11px] text-aegis-accent hover:bg-aegis-accent/20 transition"
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
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 font-mono text-xs text-aegis-text-muted">
            <div>
              Showing {Math.min(filteredAgents.length, agentOffset + 1)} to {Math.min(filteredAgents.length, agentOffset + agentLimit)} of {filteredAgents.length} records
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={agentOffset === 0}
                onClick={() => setAgentOffset((prev) => Math.max(0, prev - agentLimit))}
                className="rounded border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary hover:bg-aegis-secondary disabled:opacity-30"
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
                className="rounded border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary hover:bg-aegis-secondary disabled:opacity-30"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Merchants Table with Search & Pagination */}
      <section className="mt-8 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper">[VENDORS // ALLOWLIST MATRIX]</span>
            <h2 id="merchants-caption" className="text-sm font-semibold tracking-wide text-aegis-text-primary">
              Allowlisted Merchants ({filteredMerchants.length})
            </h2>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <input
                type="text"
                value={merchantSearch}
                onChange={(e) => {
                  setMerchantSearch(e.target.value);
                  setMerchantOffset(0);
                }}
                placeholder="Filter by vendor, domain, category..."
                className="w-64 rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
              {merchantSearch && (
                <button
                  type="button"
                  onClick={() => {
                    setMerchantSearch("");
                    setMerchantOffset(0);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 font-mono text-xs text-aegis-text-muted hover:text-aegis-text-primary"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="flex items-center gap-1.5 font-mono text-xs text-aegis-text-muted">
              <label htmlFor="merchant-limit-select">Limit:</label>
              <select
                id="merchant-limit-select"
                value={merchantLimit}
                onChange={(e) => {
                  setMerchantLimit(Number(e.target.value));
                  setMerchantOffset(0);
                }}
                className="rounded border border-aegis-border bg-aegis-card px-2 py-1 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
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
          <table className="aegis-table w-full text-left text-xs">
            <thead>
              <tr>
                <th scope="col">Merchant</th>
                <th scope="col">Domain</th>
                <th scope="col">Category</th>
                <th scope="col">Status</th>
                <th scope="col" className="text-right">Policy Action</th>
              </tr>
            </thead>
            <tbody>
              {loading && merchants.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center font-mono text-aegis-text-muted">
                    Loading merchants…
                  </td>
                </tr>
              ) : pagedMerchants.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center font-mono text-aegis-text-muted">
                    {merchantSearch ? "No merchants matching query." : "No merchants configured in allowlist."}
                  </td>
                </tr>
              ) : (
                pagedMerchants.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <div className="font-semibold text-aegis-text-primary">{m.name}</div>
                      <div className="font-mono text-[11px] text-aegis-text-faint">{m.id}</div>
                    </td>
                    <td className="font-mono text-aegis-text-muted">{m.domain}</td>
                    <td className="font-mono text-aegis-text-muted">{m.category}</td>
                    <td>
                      <StatusBadge label={m.is_allowlisted ? "ACTIVE" : "SUSPENDED"} />
                    </td>
                    <td className="text-right">
                      {hasPermission("passports:write") && (
                        <button
                          type="button"
                          onClick={() => void handleToggleMerchantAllowlist(m)}
                          className="rounded border border-aegis-border bg-aegis-card px-2.5 py-1 font-mono text-[11px] text-aegis-text-primary hover:bg-aegis-secondary transition"
                        >
                          {m.is_allowlisted ? "Revoke Allowlist" : "Allowlist"}
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
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 font-mono text-xs text-aegis-text-muted">
            <div>
              Showing {Math.min(filteredMerchants.length, merchantOffset + 1)} to {Math.min(filteredMerchants.length, merchantOffset + merchantLimit)} of {filteredMerchants.length} vendors
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={merchantOffset === 0}
                onClick={() => setMerchantOffset((prev) => Math.max(0, prev - merchantLimit))}
                className="rounded border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary hover:bg-aegis-secondary disabled:opacity-30"
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
                className="rounded border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary hover:bg-aegis-secondary disabled:opacity-30"
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