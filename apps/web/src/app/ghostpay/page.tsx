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
      if (statusFilter) qs.set("status", statusFilter);
      if (driftOnly) qs.set("drift_only", "true");

      const [invRes, payRes, agentRes] = await Promise.all([
        apiRequest<{ items?: InvestigationRecord[]; total?: number } | InvestigationRecord[]>(
          `/v1/ghostpay/investigations?${qs.toString()}`,
          {
            token: session.access_token,
            orgId: session.active_tenant_id,
          },
        ),
        apiRequest<PaymentIntentRecord[]>("/v1/guardian/payments?limit=50", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<AgentRecord[]>("/v1/guardian/agents", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
      ]);

      if (Array.isArray(invRes)) {
        setInvestigations(invRes);
        setTotalInvestigations(invRes.length);
      } else {
        setInvestigations(invRes.items || []);
        setTotalInvestigations(invRes.total || (invRes.items ? invRes.items.length : 0));
      }

      setPayments(payRes);
      setAgents(agentRes);
      if (!selectedIntentId && payRes[0]) {
        setSelectedIntentId(payRes[0].id);
      }
      if (!selectedAgentId && agentRes[0]) {
        setSelectedAgentId(agentRes[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load GhostPay forensic records");
    } finally {
      setLoading(false);
    }
  }, [driftOnly, page, pageSize, searchIntentId, selectedAgentId, selectedIntentId, session, statusFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleLaunchReplay(e: React.FormEvent) {
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
      const res = await apiRequest<InvestigationRecord>("/v1/ghostpay/investigations", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          trace_id: createTraceId.trim(),
          payment_intent_id: createTraceId.trim(),
          mode: "EXACT_HISTORICAL",
        },
      });
      setInvestigationNotice(
        `Investigation ${truncateId(res.id, 10)} recorded with consistency [${res.consistency_status}].`,
      );
      setCreateTraceId("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to record forensic investigation");
    } finally {
      setCreatingInvestigation(false);
    }
  }

  async function handleInspectAgentDna(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !selectedAgentId) return;
    setLoadingProfile(true);
    setProfileError(null);
    try {
      const profile = await apiRequest<AgentDNAProfile>(`/v1/ghostpay/agents/${selectedAgentId}/dna`, {
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setAgentProfile(profile);
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Failed to load agent DNA profile");
      setAgentProfile(null);
    } finally {
      setLoadingProfile(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(totalInvestigations / pageSize));

  return (
    <AppShell
      title="GhostPay Forensic Engine"
      subtitle="Read-only policy replay, behavioral DNA anomaly detection, and counterfactual simulation."
    >
      {error && (
        <div role="alert" className="mb-4 border border-[#4A2828] bg-[#211212] p-3 font-mono text-xs text-[#EF5350]">
          {error}
        </div>
      )}
      {investigationNotice && (
        <div role="status" className="mb-4 border border-[#3A4A28] bg-[#162112] p-3 font-mono text-xs text-aegis-accent">
          {investigationNotice}
        </div>
      )}

      {/* Replay & Investigation Launchers Grid */}
      <div className="mb-8 grid gap-4 lg:grid-cols-2">
        {/* Replay Launcher */}
        <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
          <div className="flex items-center justify-between border-b border-aegis-border pb-3">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper font-semibold">
                COUNTERFACTUAL SIMULATOR
              </span>
              <h2 className="mt-0.5 text-sm font-semibold text-aegis-text-primary">Transaction Policy Replay</h2>
            </div>
            <span className="font-mono text-[10px] text-aegis-text-faint">ZERO SIDE EFFECTS</span>
          </div>
          <p className="mt-2.5 text-xs text-aegis-text-muted">
            Replay historical authorizations against current or modified policies to detect behavioral drift and evaluate what-if constraints.
          </p>

          <form onSubmit={handleLaunchReplay} className="mt-4 space-y-3 font-mono text-xs">
            <div>
              <label htmlFor="replay-intent-select" className="block uppercase text-aegis-text-muted">
                Select Target Payment Intent
              </label>
              <select
                id="replay-intent-select"
                value={selectedIntentId}
                onChange={(e) => setSelectedIntentId(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              >
                {payments.length === 0 ? (
                  <option value="">No payment intents available</option>
                ) : (
                  payments.map((p) => (
                    <option key={p.id} value={p.id} className="bg-aegis-surface">
                      {truncateId(p.id, 14)} · {p.state} · {formatMinorCurrency(p.amount_minor, p.currency)}
                    </option>
                  ))
                )}
              </select>
            </div>
            <button
              type="submit"
              disabled={!selectedIntentId}
              className="w-full border border-aegis-copper bg-aegis-copper py-2.5 font-mono text-xs font-bold uppercase tracking-wider text-[#111513] hover:bg-[#E59A72] disabled:opacity-50 transition-colors shadow-editorial"
            >
              Launch Replay & Counterfactuals
            </button>
          </form>
        </section>

        {/* Investigation Form */}
        <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
          <div className="flex items-center justify-between border-b border-aegis-border pb-3">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                DOSSIER RECORDING
              </span>
              <h2 className="mt-0.5 text-sm font-semibold text-aegis-text-primary">Initiate Forensic Investigation</h2>
            </div>
            <span className="font-mono text-[10px] text-aegis-text-faint">POST /v1/ghostpay/investigations</span>
          </div>
          <p className="mt-2.5 text-xs text-aegis-text-muted">
            Persist an immutable audit investigation dossier for a transaction trace or suspicious payment intent.
          </p>

          <form onSubmit={handleCreateInvestigation} className="mt-4 space-y-3 font-mono text-xs">
            <div>
              <label htmlFor="investigation-trace-id" className="block uppercase text-aegis-text-muted">
                Target Trace / Payment Intent ID
              </label>
              <div className="mt-1.5 flex gap-2">
                <input
                  id="investigation-trace-id"
                  type="text"
                  value={createTraceId}
                  onChange={(e) => setCreateTraceId(e.target.value)}
                  placeholder="Paste UUID or select intent..."
                  className="flex-1 border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
                {payments.length > 0 && (
                  <select
                    aria-label="Quick select payment intent"
                    onChange={(e) => {
                      if (e.target.value) setCreateTraceId(e.target.value);
                    }}
                    value=""
                    className="border border-aegis-border bg-aegis-card px-2 text-xs text-aegis-text-muted focus:outline-none"
                  >
                    <option value="">SELECT…</option>
                    {payments.map((p) => (
                      <option key={p.id} value={p.id} className="bg-aegis-surface">
                        {truncateId(p.id, 10)} [{p.state}]
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>
            <button
              type="submit"
              disabled={creatingInvestigation || !createTraceId.trim()}
              className="w-full border border-aegis-accent bg-aegis-accent py-2.5 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50 transition-colors shadow-editorial"
            >
              {creatingInvestigation ? "Recording Dossier…" : "Record Investigation Dossier"}
            </button>
          </form>
        </section>
      </div>

      {/* Agent DNA Profile Inspector Panel */}
      <section className="mb-8 border border-aegis-border bg-aegis-surface p-5 rounded-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
              BEHAVIORAL FINGERPRINTING
            </span>
            <h2 className="mt-0.5 text-sm font-semibold text-aegis-text-primary">Agent DNA Profile Inspector</h2>
            <p className="mt-1 text-xs text-aegis-text-muted">
              Inspect statistical behavioral baselines, spending entropy, merchant affinities, and anomaly drift indicators.
            </p>
          </div>
          <form onSubmit={handleInspectAgentDna} className="flex flex-wrap items-center gap-2 font-mono text-xs">
            <select
              aria-label="Select Agent for DNA inspection"
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              className="border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
            >
              <option value="">Select an agent...</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id} className="bg-aegis-surface">
                  {a.name} ({truncateId(a.id, 8)})
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={loadingProfile || !selectedAgentId}
              className="border border-aegis-accent bg-aegis-accent px-3 py-1.5 font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50 transition-colors"
            >
              {loadingProfile ? "Loading…" : "Inspect DNA"}
            </button>
          </form>
        </div>

        {profileError && (
          <div className="mt-4 border border-[#4A2828] bg-[#211212] p-3 font-mono text-xs text-[#EF5350]">
            {profileError}
          </div>
        )}

        {agentProfile ? (
          <div className="mt-5 space-y-4 font-mono">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="border border-aegis-border bg-aegis-card p-3.5">
                <span className="text-[10px] uppercase tracking-wider text-aegis-text-faint">AGENT IDENTITY</span>
                <div className="mt-1 text-xs font-semibold text-aegis-text-primary">{agentProfile.name}</div>
                <div className="font-mono text-[10px] text-aegis-text-faint mt-0.5">{agentProfile.agent_id}</div>
              </div>

              <div className="border border-aegis-border bg-aegis-card p-3.5">
                <span className="text-[10px] uppercase tracking-wider text-aegis-text-faint">RISK SCORE</span>
                <div className="mt-1 flex items-center gap-2">
                  <span
                    className={`border px-1.5 py-0.5 text-xs font-bold uppercase ${
                      agentProfile.risk_score > 70
                        ? "border-[#4A2828] bg-[#211212] text-[#EF5350]"
                        : agentProfile.risk_score > 30
                          ? "border-[#4A3728] bg-[#211812] text-aegis-copper"
                          : "border-[#3A4A28] bg-[#162112] text-aegis-accent"
                    }`}
                  >
                    SCORE: {agentProfile.risk_score}
                  </span>
                  <span className="text-[10px] text-aegis-text-muted">
                    {agentProfile.risk_score > 70 ? "HIGH RISK" : agentProfile.risk_score > 30 ? "MODERATE" : "LOW RISK"}
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-aegis-text-faint">VERSION: {agentProfile.profile_version}</div>
              </div>

              <div className="border border-aegis-border bg-aegis-card p-3.5">
                <span className="text-[10px] uppercase tracking-wider text-aegis-text-faint">BEHAVIORAL ENTROPY</span>
                <div className="mt-1 text-xs font-semibold text-aegis-text-primary">
                  ENTROPY: <span className="text-aegis-accent tabular-nums">{Number(agentProfile.spending_entropy).toFixed(2)}</span>
                </div>
                <div className="text-[10px] text-aegis-text-faint mt-0.5">
                  ANOMALIES: <span className={agentProfile.anomaly_count > 0 ? "text-aegis-copper font-bold" : "text-aegis-text-muted"}>{agentProfile.anomaly_count}</span>
                </div>
              </div>

              <div className="border border-aegis-border bg-aegis-card p-3.5">
                <span className="text-[10px] uppercase tracking-wider text-aegis-text-faint">PROFILE CHRONO</span>
                <div className="mt-1 text-xs text-aegis-text-muted">{formatIsoDateTime(agentProfile.last_updated)}</div>
                <div className="text-[10px] text-aegis-text-faint mt-0.5">
                  {agentProfile.drift_indicators?.length || 0} DRIFT INDICATORS
                </div>
              </div>
            </div>

            {agentProfile.drift_indicators && agentProfile.drift_indicators.length > 0 && (
              <div className="border border-[#4A3728] bg-[#211812] p-3 text-xs text-aegis-copper">
                <span className="font-semibold uppercase tracking-wider">ACTIVE DRIFT INDICATORS: </span>
                <span>{agentProfile.drift_indicators.join(", ")}</span>
              </div>
            )}

            {agentProfile.merchant_affinities && agentProfile.merchant_affinities.length > 0 && (
              <div tabIndex={0} role="region" aria-label="Agent merchant affinities" className="table-wrapper">
                <table className="aegis-table">
                  <thead>
                    <tr>
                      <th scope="col">MERCHANT IDENTIFIER</th>
                      <th scope="col" className="text-right">TRANSACTION COUNT</th>
                      <th scope="col" className="text-right">TOTAL SPENT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentProfile.merchant_affinities.map((m, idx) => (
                      <tr key={m.merchant_id || idx}>
                        <td className="font-mono text-xs text-aegis-text-primary">{m.merchant_id}</td>
                        <td className="text-right font-mono text-xs text-aegis-text-muted tabular-nums">{m.count}</td>
                        <td className="text-right font-mono text-xs font-semibold text-aegis-accent tabular-nums">
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
          <div className="mt-4 border border-dashed border-aegis-border bg-aegis-card p-6 text-center font-mono text-xs text-aegis-text-muted">
            SELECT AN AGENT TO REVEAL THEIR STATISTICAL DNA PROFILE AND SPENDING ENTROPY.
          </div>
        )}
      </section>

      {/* Persisted Replay Investigations Table & Filters */}
      <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-text-faint">
              INVESTIGATION REPOSITORY
            </span>
            <h2 className="text-sm font-semibold text-aegis-text-primary">
              Persisted Replay Investigations ({totalInvestigations})
            </h2>
          </div>

          {/* Search & Filters */}
          <div className="flex flex-wrap items-center gap-3 font-mono text-xs">
            <input
              type="text"
              aria-label="Filter by payment intent ID"
              placeholder="Search Intent UUID..."
              value={searchIntentId}
              onChange={(e) => {
                setSearchIntentId(e.target.value);
                setPage(1);
              }}
              className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
            />
            <label className="flex items-center gap-1.5 text-aegis-text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={driftOnly}
                onChange={(e) => {
                  setDriftOnly(e.target.checked);
                  setPage(1);
                }}
                className="h-3 w-3 border-aegis-border bg-aegis-card text-aegis-accent focus:ring-0"
              />
              <span>DRIFT ONLY</span>
            </label>
            <select
              aria-label="Filter by consistency status"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary focus:outline-none"
            >
              <option value="">ALL STATUSES</option>
              <option value="CONSISTENT">CONSISTENT</option>
              <option value="DRIFT_DETECTED">DRIFT_DETECTED</option>
              <option value="INTEGRITY_FAILURE">INTEGRITY_FAILURE</option>
              <option value="INCOMPLETE_EVIDENCE">INCOMPLETE_EVIDENCE</option>
            </select>
          </div>
        </div>

        <div tabIndex={0} role="region" aria-label="GhostPay forensic investigations" className="table-wrapper mt-4">
          <table className="aegis-table">
            <thead>
              <tr>
                <th scope="col">INVESTIGATION ID</th>
                <th scope="col">PAYMENT INTENT</th>
                <th scope="col">REPLAY MODE</th>
                <th scope="col">OUTCOME TRANSITION</th>
                <th scope="col">CONSISTENCY</th>
                <th scope="col">ANOMALIES</th>
                <th scope="col">RECORDED AT</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                    RETRIEVING INVESTIGATION DOSSIERS…
                  </td>
                </tr>
              ) : investigations.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                    NO PERSISTED REPLAY INVESTIGATIONS MATCH CURRENT CRITERIA.
                  </td>
                </tr>
              ) : (
                investigations.map((inv) => (
                  <tr key={inv.id}>
                    <td className="font-mono text-xs text-aegis-text-muted">{truncateId(inv.id, 10)}</td>
                    <td className="font-mono text-xs text-aegis-accent font-semibold">
                      <Link href={`/ghostpay/replay/${inv.payment_intent_id}`} className="hover:underline">
                        {truncateId(inv.payment_intent_id, 14)}
                      </Link>
                    </td>
                    <td className="font-mono text-xs text-aegis-text-muted">{inv.mode}</td>
                    <td className="font-mono text-xs">
                      <span className="text-aegis-text-faint">{inv.original_outcome}</span>{" "}
                      <span className="text-aegis-accent">→</span>{" "}
                      <span className="font-semibold text-aegis-text-primary">{inv.recomputed_outcome}</span>
                    </td>
                    <td>
                      <StatusBadge label={inv.consistency_status} />
                    </td>
                    <td className="font-mono text-xs text-aegis-text-muted">
                      {!inv.anomalies || inv.anomalies.length === 0 ? (
                        <span className="text-aegis-text-faint">NONE</span>
                      ) : (
                        <span className="text-aegis-copper font-medium">{inv.anomalies.join(", ")}</span>
                      )}
                    </td>
                    <td className="font-mono text-xs text-aegis-text-muted tabular-nums">
                      {formatIsoDateTime(inv.created_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-aegis-border pt-3 font-mono text-xs text-aegis-text-faint mt-4">
          <div className="flex items-center gap-2">
            <span>ROWS:</span>
            <select
              aria-label="Rows per page"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="border border-aegis-border bg-aegis-card px-2 py-0.5 text-xs text-aegis-text-primary focus:outline-none"
            >
              <option value="10">10</option>
              <option value="25">25</option>
              <option value="50">50</option>
            </select>
            <span className="ml-2">
              SHOWING {totalInvestigations === 0 ? 0 : (page - 1) * pageSize + 1}–
              {Math.min(page * pageSize, totalInvestigations)} OF {totalInvestigations}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
            >
              PREV
            </button>
            <span className="px-2">
              PAGE {page} OF {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
            >
              NEXT
            </button>
          </div>
        </div>
      </section>
    </AppShell>
  );
}
