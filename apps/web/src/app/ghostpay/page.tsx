"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type InvestigationRecord, type PaymentIntentRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

export default function GhostPayPage() {
  const { session } = useAuth();
  const router = useRouter();
  const [investigations, setInvestigations] = useState<InvestigationRecord[]>([]);
  const [payments, setPayments] = useState<PaymentIntentRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [driftOnly, setDriftOnly] = useState(false);
  const [selectedIntentId, setSelectedIntentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ limit: "100" });
      if (statusFilter) qs.set("consistency_status", statusFilter);
      if (driftOnly) qs.set("drift_detected", "true");

      const [invResp, payResp] = await Promise.all([
        apiRequest<{ items: InvestigationRecord[]; total: number }>(`/v1/ghostpay/investigations?${qs.toString()}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<PaymentIntentRecord[]>("/v1/guardian/payments?limit=50", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
      ]);
      setInvestigations(invResp.items);
      setPayments(payResp);
      setSelectedIntentId((prev) => prev || payResp[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load GhostPay investigations");
    } finally {
      setLoading(false);
    }
  }, [driftOnly, session, statusFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  function handleLaunchReplay(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedIntentId) return;
    router.push(`/ghostpay/replay/${selectedIntentId}`);
  }

  return (
    <AppShell
      title="GhostPay Forensics & Replay"
      subtitle="Read-only deterministic policy replay, counterfactual simulation, and anomaly detection."
    >
      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <section className="mb-6 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <h2 className="text-sm font-semibold text-white">Launch Forensic Replay Session</h2>
        <p className="mt-0.5 text-xs text-slate-400">
          Replays run with <span className="font-mono text-sky-300">executed_payment=false</span> — zero live gateway side effects.
        </p>
        <form onSubmit={handleLaunchReplay} className="mt-4 flex flex-wrap items-end gap-3">
          <div className="min-w-[280px] flex-1">
            <label htmlFor="replay-intent-select" className="block text-xs font-medium text-slate-300">
              Select Payment Intent
            </label>
            <select
              id="replay-intent-select"
              value={selectedIntentId}
              onChange={(e) => setSelectedIntentId(e.target.value)}
              className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
            >
              {payments.map((p) => (
                <option key={p.id} value={p.id}>
                  {truncateId(p.id, 12)} · {p.state} · {formatMinorCurrency(p.amount_minor, p.currency)}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={!selectedIntentId}
            className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
          >
            Inspect Replay & Counterfactuals
          </button>
        </form>
      </section>

      <section className="rounded-xl border border-aegis-border bg-aegis-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border px-5 py-3">
          <h2 className="text-sm font-semibold text-white">Persisted Replay Investigations</h2>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="flex items-center gap-1.5 text-slate-300">
              <input
                type="checkbox"
                checked={driftOnly}
                onChange={(e) => setDriftOnly(e.target.checked)}
                className="rounded border-aegis-border bg-aegis-panel"
              />
              Drift detected only
            </label>
            <select
              aria-label="Filter by consistency status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-white"
            >
              <option value="">All Statuses</option>
              <option value="CONSISTENT">CONSISTENT</option>
              <option value="DRIFT_DETECTED">DRIFT_DETECTED</option>
              <option value="INTEGRITY_FAILURE">INTEGRITY_FAILURE</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">GhostPay forensic investigations</caption>
            <thead className="border-b border-aegis-border bg-aegis-panel/60 text-xs uppercase text-slate-400">
              <tr>
                <th className="px-4 py-3">Investigation</th>
                <th className="px-4 py-3">Payment Intent</th>
                <th className="px-4 py-3">Mode</th>
                <th className="px-4 py-3">Outcomes</th>
                <th className="px-4 py-3">Consistency</th>
                <th className="px-4 py-3">Anomalies</th>
                <th className="px-4 py-3">Created</th>
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
                    No persisted GhostPay investigations yet. Launch a replay session above to record one.
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
                      {inv.anomalies.length === 0 ? "None" : inv.anomalies.join(", ")}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">{formatIsoDateTime(inv.created_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </AppShell>
  );
}
