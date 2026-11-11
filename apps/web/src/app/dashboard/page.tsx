"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bot, CheckCircle2, RefreshCw, Scale, Shield, Wallet } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type OverviewMetrics } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

export default function DashboardPage() {
  const { session } = useAuth();
  const [metrics, setMetrics] = useState<OverviewMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadMetrics = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest<OverviewMetrics>("/v1/overview/metrics", {
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setMetrics(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load overview metrics");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void loadMetrics();
  }, [loadMetrics]);

  return (
    <AppShell
      title="Platform Overview"
      subtitle="Real-time governance metrics, budget posture, and cryptographically chained events"
    >
      <div className="mb-6 flex items-center justify-between">
        <div className="text-xs text-slate-400">
          Organization ID: <span className="font-mono text-slate-300">{session?.active_tenant_id}</span>
        </div>
        <button
          type="button"
          onClick={() => void loadMetrics()}
          className="inline-flex items-center gap-2 rounded-lg border border-aegis-border bg-aegis-surface px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div role="status" className="mb-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
        </div>
      )}

      {loading && !metrics ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((idx) => (
            <div key={idx} className="h-28 animate-pulse rounded-xl border border-aegis-border bg-aegis-surface" />
          ))}
        </div>
      ) : metrics ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Available Passport Budget</span>
                <Wallet className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-white">
                {formatMinorCurrency(metrics.budget.available_minor)}
              </div>
              <div className="mt-1 text-xs text-slate-400">
                Spent {formatMinorCurrency(metrics.budget.spent_minor)} · Reserved{" "}
                {formatMinorCurrency(metrics.budget.reserved_minor)}
              </div>
            </div>

            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>AI Agents & Approvals</span>
                <Bot className="h-4 w-4 text-sky-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-white">
                {metrics.agents.active} / {metrics.agents.total} Active
              </div>
              <div className="mt-1 text-xs text-slate-400">
                Pending Human Approvals:{" "}
                <Link href="/payments" className="font-semibold text-amber-300 underline">
                  {metrics.pending_approvals}
                </Link>
              </div>
            </div>

            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Payments & Disputes</span>
                <Scale className="h-4 w-4 text-amber-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-white">{metrics.payments.total} Total</div>
              <div className="mt-1 text-xs text-slate-400">
                Succeeded: {metrics.payments.by_state.SUCCEEDED ?? 0} · Open Disputes: {metrics.open_disputes}
              </div>
            </div>

            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Integrity & Outbox Alerts</span>
                {metrics.risk_alerts > 0 ? (
                  <AlertTriangle className="h-4 w-4 text-rose-400" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                )}
              </div>
              <div className="mt-2 text-2xl font-bold text-white">{metrics.risk_alerts}</div>
              <div className="mt-1 text-xs text-slate-400">
                Dead-Letter Outbox Events: {metrics.dead_letter_outbox}
              </div>
            </div>
          </div>

          <section className="mt-8">
            <div className="mb-3 flex items-center justify-between">
              <h2 id="recent-events-caption" className="flex items-center gap-2 text-base font-semibold text-white">
                <Shield className="h-4 w-4 text-sky-400" />
                Recent Hash-Chained Financial Events
              </h2>
              <Link href="/audit" className="text-xs font-medium text-sky-400 hover:underline">
                Open Chain Verifier →
              </Link>
            </div>

            {metrics.recent_events.length === 0 ? (
              <div className="rounded-xl border border-dashed border-aegis-border bg-aegis-surface p-8 text-center text-sm text-slate-400">
                No financial events recorded for this organization yet. Register an agent and spending passport to begin,
                or run a GhostPay/DisputeOS sandbox demo workflow.
              </div>
            ) : (
              <div tabIndex={0} role="region" aria-labelledby="recent-events-caption" className="table-wrapper">
                <table className="aegis-table">
                  <thead>
                    <tr>
                      <th scope="col">Seq</th>
                      <th scope="col">Event Type</th>
                      <th scope="col">Actor</th>
                      <th scope="col">Correlation ID</th>
                      <th scope="col">Event Hash</th>
                      <th scope="col">Occurred</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.recent_events.map((ev) => (
                      <tr key={ev.id}>
                        <td className="font-mono text-xs text-slate-300">#{ev.sequence_number}</td>
                        <td>
                          <StatusBadge label={ev.event_type} />
                        </td>
                        <td className="text-xs text-slate-300">
                          {ev.actor_type} ({truncateId(ev.actor_id, 12)})
                        </td>
                        <td className="font-mono text-xs text-sky-300">{truncateId(ev.correlation_id, 12)}</td>
                        <td className="font-mono text-xs text-slate-400">{truncateId(ev.event_hash, 14)}</td>
                        <td className="text-xs text-slate-400">{formatIsoDateTime(ev.occurred_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </AppShell>
  );
}
