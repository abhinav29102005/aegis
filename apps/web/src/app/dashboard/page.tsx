"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Compass,
  RefreshCw,
  Scale,
  Shield,
  Sparkles,
  Wallet,
} from "lucide-react";
import { AppShell } from "@/components/AppShell";
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
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-slate-400">
          Organization ID: <span className="font-mono text-slate-300">{session?.active_tenant_id}</span>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/onboarding"
            className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-1.5 text-xs font-medium text-sky-300 hover:bg-sky-500/20"
          >
            <Compass className="h-3.5 w-3.5" />
            <span>Onboarding Wizard</span>
          </Link>
          <button
            type="button"
            onClick={() => void loadMetrics()}
            className="inline-flex items-center gap-2 rounded-lg border border-aegis-border bg-aegis-surface px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="mb-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200"
        >
          {error}
        </div>
      )}

      {/* Quick Setup Checklist if no agents or budgets initialized */}
      {metrics && metrics.agents.total === 0 && (
        <div className="mb-6 rounded-2xl border border-sky-500/30 bg-gradient-to-r from-sky-500/10 via-slate-900 to-aegis-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-500/20 text-sky-400">
                <Sparkles className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-white">Initial Organization Setup Checklist</h2>
                <p className="mt-0.5 text-xs text-slate-300">
                  Ready to empower autonomous purchasing? Complete the setup wizard to register your first agent and spending passport.
                </p>
              </div>
            </div>
            <Link
              href="/onboarding"
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400"
            >
              <span>Launch Guided Onboarding</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
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
                      <th scope="col">Seq #</th>
                      <th scope="col">Event Type</th>
                      <th scope="col">Actor</th>
                      <th scope="col">Previous Hash</th>
                      <th scope="col">Event Hash</th>
                      <th scope="col">Timestamp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.recent_events.map((evt) => (
                      <tr key={evt.id}>
                        <td className="font-mono text-slate-300">{evt.sequence_number}</td>
                        <td className="font-semibold text-white">{evt.event_type}</td>
                        <td className="text-slate-300">
                          {evt.actor_type}: {truncateId(evt.actor_id, 10)}
                        </td>
                        <td className="font-mono text-slate-400">
                          {evt.previous_event_hash ? truncateId(evt.previous_event_hash, 12) : "GENESIS"}
                        </td>
                        <td className="font-mono text-sky-300">{truncateId(evt.event_hash, 12)}</td>
                        <td className="text-slate-400">{formatIsoDateTime(evt.occurred_at)}</td>
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
