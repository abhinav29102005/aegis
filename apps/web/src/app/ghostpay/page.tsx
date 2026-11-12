"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  apiRequest,
  type AgentDNAProfile,
  type AgentRecord,
  type InvestigationRecord,
  type PaymentIntentRecord,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

export default function GhostPayPage() {
  const { session } = useAuth();
  const router = useRouter();

  // Investigations & Replay state
  const [investigations, setInvestigations] = useState<InvestigationRecord[]>([]);
  const [totalInvestigations, setTotalInvestigations] = useState(0);
  const [payments, setPayments] = useState<PaymentIntentRecord[]>([]);
  const [agents, setAgents] = useState<AgentRecord[]>([]);

  // Search & Filter state
  const [searchIntentId, setSearchIntentId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [driftOnly, setDriftOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Replay launcher state
  const [selectedIntentId, setSelectedIntentId] = useState("");

  // Create investigation form state
  const [createTraceId, setCreateTraceId] = useState("");
  const [creatingInvestigation, setCreatingInvestigation] = useState(false);
  const [investigationNotice, setInvestigationNotice] = useState<string | null>(null);

  // Agent DNA Inspector state
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [agentProfile, setAgentProfile] = useState<AgentDNAProfile | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const qs = new URLSearchParams({
        limit: String(pageSize),
        offset: String(offset),
      });
      if (searchIntentId.trim()) qs.set("payment_intent_id", searchIntentId.trim());
      if (statusFilter) qs.set("consistency_status", statusFilter);
      if (driftOnly) qs.set("drift_detected", "true");

      const [invResp, payResp, agtResp] = await Promise.all([
        apiRequest<{ items: InvestigationRecord[]; total: number }>(
          `/v1/ghostpay/investigations?${qs.toString()}`,
          {
            token: session.access_token,
            orgId: session.active_tenant_id,
          },
        ),
        apiRequest<PaymentIntentRecord[]>("/v1/guardian/payments?limit=50", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }).catch(() => [] as PaymentIntentRecord[]),
        apiRequest<AgentRecord[]>("/v1/guardian/agents", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }).catch(() => [] as AgentRecord[]),
      ]);

      setInvestigations(invResp.items || []);
      setTotalInvestigations(invResp.total || (invResp.items ? invResp.items.length : 0));
      setPayments(payResp);
      setAgents(agtResp);

      if (!selectedIntentId && payResp.length > 0) {
        setSelectedIntentId(payResp[0].id);
      }
      if (!createTraceId && payResp.length > 0) {
        setCreateTraceId(payResp[0].id);
      }
      if (!selectedAgentId && agtResp.length > 0) {
        setSelectedAgentId(agtResp[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load GhostPay investigations");
    } finally {
      setLoading(false);
    }
  }, [createTraceId, driftOnly, page, pageSize, searchIntentId, selectedAgentId, selectedIntentId, session, statusFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  function handleLaunchReplay(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedIntentId) return;
    router.push(`/ghostpay/replay/${selectedIntentId}`);
  }

  async function handleCreateInvestigation(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !createTraceId.trim()) return;
    setCreatingInvestigation(true);
    setInvestigationNotice(null);
    setError(null);
    try {
      await apiRequest("/v1/ghostpay/investigations", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          trace_id: createTraceId.trim(),
        },
      });
      setInvestigationNotice(`Investigation successfully recorded for trace ${truncateId(createTraceId.trim(), 12)}.`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create investigation");
    } finally {
      setCreatingInvestigation(false);
    }
  }

  async function handleInspectAgentDna(e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!session || !selectedAgentId.trim()) return;
    setLoadingProfile(true);
    setProfileError(null);
    try {
      const profile = await apiRequest<AgentDNAProfile>(
        `/v1/ghostpay/agents/${selectedAgentId.trim()}/profile`,
        {
          token: session.access_token,
          orgId: session.active_tenant_id,
        },
      );
      setAgentProfile(profile);
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Failed to load Agent DNA profile");
      setAgentProfile(null);
    } finally {
      setLoadingProfile(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(totalInvestigations / pageSize));

  return (
    <AppShell
      title="GhostPay Forensics & Replay"
      subtitle="Read-only deterministic policy replay, counterfactual simulation, Agent DNA anomaly detection, and provenance timelines."
    >
      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}
      {investigationNotice && (
        <div role="status" className="mb-4 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
          {investigationNotice}
        </div>
      )}

      {/* Action Panels Grid: Launch Replay & Create Investigation */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        {/* Launch Forensic Replay Session */}
        <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
          <h2 className="text-sm font-semibold text-white">Launch Forensic Replay Session</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Replays execute with <span className="font-mono text-sky-300">executed_payment=false</span> — guaranteed read-only with zero gateway side-effects.
          </p>
          <form onSubmit={handleLaunchReplay} className="mt-4 space-y-3">
            <div>
              <label htmlFor="replay-intent-select" className="block text-xs font-medium text-slate-300">
                Select Payment Intent
              </label>
              <select
                id="replay-intent-select"
                value={selectedIntentId}
                onChange={(e) => setSelectedIntentId(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              >
                {payments.length === 0 ? (
                  <option value="">No payments available</option>
                ) : (
                  payments.map((p) => (
                    <option key={p.id} value={p.id}>
                      {truncateId(p.id, 12)} · {p.state} · {formatMinorCurrency(p.amount_minor, p.currency)}
                    </option>
                  ))
                )}
              </select>
            </div>
            <button
              type="submit"
              disabled={!selectedIntentId}
              className="w-full rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
            >
              Inspect Replay & Counterfactuals
            </button>
          </form>
        </section>

        {/* POST /v1/ghostpay/investigations creation form */}
        <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
          <h2 className="text-sm font-semibold text-white">Initiate Forensic Investigation</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Record a formal forensic investigation dossier from a transaction trace or payment intent (<span className="font-mono text-sky-300">POST /v1/ghostpay/investigations</span>).
          </p>
          <form onSubmit={handleCreateInvestigation} className="mt-4 space-y-3">
            <div>
              <label htmlFor="investigation-trace-id" className="block text-xs font-medium text-slate-300">
                Target Trace / Payment Intent ID
              </label>
              <div className="mt-1 flex gap-2">
                <input
                  id="investigation-trace-id"
                  type="text"
                  value={createTraceId}
                  onChange={(e) => setCreateTraceId(e.target.value)}
                  placeholder="Paste UUID or select payment intent..."
                  className="flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 font-mono text-xs text-white"
                />
                {payments.length > 0 && (
                  <select
                    aria-label="Quick select payment intent"
                    onChange={(e) => {
                      if (e.target.value) setCreateTraceId(e.target.value);
                    }}
                    value=""
                    className="rounded-lg border border-aegis-border bg-aegis-panel px-2 text-xs text-slate-300"
                  >
                    <option value="">Select...</option>
                    {payments.map((p) => (
                      <option key={p.id} value={p.id}>
                        {truncateId(p.id, 10)} ({p.state})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>
            <button
              type="submit"
              disabled={creatingInvestigation || !createTraceId.trim()}
              className="w-full rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400 disabled:opacity-50"
            >
              {creatingInvestigation ? "Recording Investigation…" : "Create Investigation Record"}
            </button>
          </form>
        </section>
      </div>

      {/* Agent DNA Profile Inspector Panel */}
      <section className="mb-6 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <div>
            <h2 className="text-sm font-semibold text-white">Agent DNA Profile Inspector</h2>
            <p className="mt-0.5 text-xs text-slate-400">
              Inspect statistical behavioral profiles, spending entropy, merchant affinities, and anomaly drift indicators.
            </p>
          </div>
          <form onSubmit={handleInspectAgentDna} className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Select Agent for DNA inspection"
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs text-white"
            >
              <option value="">Select an agent...</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({truncateId(a.id, 8)})
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={loadingProfile || !selectedAgentId}
              className="rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
            >
              {loadingProfile ? "Loading DNA…" : "Inspect Profile"}
            </button>
          </form>
        </div>

        {profileError && (
          <div className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
            {profileError}
          </div>
        )}

        {agentProfile ? (
          <div className="mt-4 space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                <span className="text-[11px] uppercase tracking-wide text-slate-400">Agent Name</span>
                <div className="mt-1 font-semibold text-white">{agentProfile.name}</div>
                <div className="font-mono text-[10px] text-slate-400">{agentProfile.agent_id}</div>
              </div>

              <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                <span className="text-[11px] uppercase tracking-wide text-slate-400">Risk Assessment</span>
                <div className="mt-1 flex items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-bold ${
                      agentProfile.risk_score > 70
                        ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                        : agentProfile.risk_score > 30
                          ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                          : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                    }`}
                  >
                    Score: {agentProfile.risk_score}
                  </span>
                  <span className="text-xs text-slate-300">
                    {agentProfile.risk_score > 70 ? "High Risk" : agentProfile.risk_score > 30 ? "Moderate" : "Low Risk"}
                  </span>
                </div>
                <div className="mt-1 text-[11px] text-slate-400">Version: {agentProfile.profile_version}</div>
              </div>

              <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                <span className="text-[11px] uppercase tracking-wide text-slate-400">Behavioral Metrics</span>
                <div className="mt-1 text-sm font-medium text-white">
                  Entropy: <span className="font-mono text-sky-300">{Number(agentProfile.spending_entropy).toFixed(2)}</span>
                </div>
                <div className="text-xs text-slate-300">
                  Anomalies: <span className="font-semibold text-amber-300">{agentProfile.anomaly_count}</span>
                </div>
              </div>

              <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                <span className="text-[11px] uppercase tracking-wide text-slate-400">Profile Updated</span>
                <div className="mt-1 text-xs text-white">{formatIsoDateTime(agentProfile.last_updated)}</div>
                <div className="text-[10px] text-slate-400">
                  {agentProfile.drift_indicators?.length || 0} drift indicators active
                </div>
              </div>
            </div>

            {agentProfile.drift_indicators && agentProfile.drift_indicators.length > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
                <span className="font-semibold">Active Drift Indicators: </span>
                {agentProfile.drift_indicators.join(", ")}
              </div>
            )}

            {agentProfile.merchant_affinities && agentProfile.merchant_affinities.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-aegis-border bg-aegis-panel">
                <table className="w-full text-left text-xs">
                  <caption className="sr-only">Agent merchant affinities</caption>
                  <thead className="border-b border-aegis-border bg-slate-900/40 uppercase text-slate-400">
                    <tr>
                      <th scope="col" className="px-3 py-2">Merchant ID</th>
                      <th scope="col" className="px-3 py-2 text-right">Transaction Count</th>
                      <th scope="col" className="px-3 py-2 text-right">Total Spent</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-aegis-border">
                    {agentProfile.merchant_affinities.map((m, idx) => (
                      <tr key={m.merchant_id || idx} className="hover:bg-slate-800/40">
                        <td className="px-3 py-2 font-mono text-slate-300">{m.merchant_id}</td>
                        <td className="px-3 py-2 text-right text-slate-300">{m.count}</td>
                        <td className="px-3 py-2 text-right font-medium text-white">
                          {formatMinorCurrency(m.total_minor, "USD")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : (
          <div className="mt-4 rounded-lg border border-dashed border-aegis-border p-4 text-center text-xs text-slate-400">
            Select an agent from the dropdown above and click &quot;Inspect Profile&quot; to inspect their behavioral DNA profile.
          </div>
        )}
      </section>

      {/* Persisted Replay Investigations Table & Filters */}
      <section className="rounded-xl border border-aegis-border bg-aegis-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border px-5 py-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-white">Persisted Replay Investigations</h2>
            <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
              {totalInvestigations} total
            </span>
          </div>

          {/* Search & Filters */}
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <input
              type="text"
              aria-label="Filter by payment intent ID"
              placeholder="Search Payment Intent ID..."
              value={searchIntentId}
              onChange={(e) => {
                setSearchIntentId(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-white placeholder-slate-500"
            />
            <label className="flex items-center gap-1.5 text-slate-300">
              <input
                type="checkbox"
                checked={driftOnly}
                onChange={(e) => {
                  setDriftOnly(e.target.checked);
                  setPage(1);
                }}
                className="rounded border-aegis-border bg-aegis-panel"
              />
              Drift only
            </label>
            <select
              aria-label="Filter by consistency status"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-white"
            >
              <option value="">All Statuses</option>
              <option value="CONSISTENT">CONSISTENT</option>
              <option value="DRIFT_DETECTED">DRIFT_DETECTED</option>
              <option value="INTEGRITY_FAILURE">INTEGRITY_FAILURE</option>
              <option value="INCOMPLETE_EVIDENCE">INCOMPLETE_EVIDENCE</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">GhostPay forensic investigations</caption>
            <thead className="border-b border-aegis-border bg-aegis-panel/60 text-xs uppercase text-slate-400">
              <tr>
                <th scope="col" className="px-4 py-3">Investigation</th>
                <th scope="col" className="px-4 py-3">Payment Intent</th>
                <th scope="col" className="px-4 py-3">Mode</th>
                <th scope="col" className="px-4 py-3">Outcomes</th>
                <th scope="col" className="px-4 py-3">Consistency</th>
                <th scope="col" className="px-4 py-3">Anomalies</th>
                <th scope="col" className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-aegis-border">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                    Loading forensic investigations…
                  </td>
                </tr>
              ) : investigations.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                    No persisted GhostPay investigations matched the criteria.
                  </td>
                </tr>
              ) : (
                investigations.map((inv) => (
                  <tr key={inv.id} className="hover:bg-slate-800/30">
                    <td className="px-4 py-3 font-mono text-xs text-slate-300">{truncateId(inv.id, 10)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-sky-300">
                      <Link href={`/ghostpay/replay/${inv.payment_intent_id}`} className="hover:underline">
                        {truncateId(inv.payment_intent_id, 12)}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-300">{inv.mode}</td>
                    <td className="px-4 py-3 text-xs">
                      <span className="text-slate-300">{inv.original_outcome}</span> →{" "}
                      <span className="font-semibold text-white">{inv.recomputed_outcome}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge label={inv.consistency_status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-300">
                      {!inv.anomalies || inv.anomalies.length === 0 ? "None" : inv.anomalies.join(", ")}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">{formatIsoDateTime(inv.created_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-aegis-border px-5 py-3 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <span>Rows per page:</span>
            <select
              aria-label="Rows per page"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="rounded border border-aegis-border bg-aegis-panel px-2 py-0.5 text-xs text-white"
            >
              <option value="10">10</option>
              <option value="25">25</option>
              <option value="50">50</option>
            </select>
            <span className="ml-2">
              Showing {totalInvestigations === 0 ? 0 : (page - 1) * pageSize + 1}–
              {Math.min(page * pageSize, totalInvestigations)} of {totalInvestigations}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
            >
              Previous
            </button>
            <span className="px-2">
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="rounded border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </section>
    </AppShell>
  );
}
