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
      title="Platform Operations"
      subtitle="Real-time governance telemetry, passport liquidity, and cryptographically verified event stream"
    >
      {/* Control bar */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-aegis-border pb-3 text-xs font-mono">
        <div className="flex items-center gap-2 text-aegis-text-muted">
          <span className="text-aegis-text-faint">TENANT SCOPE:</span>
          <span className="border border-aegis-border bg-aegis-card px-2 py-0.5 text-aegis-text-primary">
            {session?.active_tenant_id}
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          <Link
            href="/onboarding"
            className="inline-flex items-center gap-1.5 border border-aegis-border bg-aegis-surface px-3 py-1.5 text-xs font-mono text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary transition-colors"
          >
            <Compass className="h-3.5 w-3.5 text-aegis-accent" />
            <span>SETUP WIZARD</span>
          </Link>
          <button
            type="button"
            onClick={() => void loadMetrics()}
            className="inline-flex items-center gap-1.5 border border-aegis-border bg-aegis-surface px-3 py-1.5 text-xs font-mono text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary transition-colors"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin text-aegis-accent" : ""}`} />
            <span>REFRESH</span>
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="mb-6 border border-[#4A2828] bg-[#211212] p-4 font-mono text-xs text-[#EF5350]"
        >
          <div className="flex items-center gap-2 font-bold uppercase tracking-wider">
            <AlertTriangle className="h-4 w-4 shrink-0 text-[#EF5350]" />
            <span>Telemetry Acquisition Error</span>
          </div>
          <p className="mt-1 text-aegis-text-muted">{error}</p>
        </div>
      )}

      {/* Quick Setup Checklist */}
      {metrics && metrics.agents.total === 0 && (
        <div className="mb-6 border border-aegis-border-active bg-aegis-surface p-5 rounded-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center border border-aegis-accent/40 bg-aegis-accent/10 text-aegis-accent">
                <Sparkles className="h-4 w-4" />
              </div>
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                  INITIALIZATION REQUIRED
                </span>
                <h2 className="mt-0.5 text-sm font-semibold text-aegis-text-primary">
                  No Autonomous Agents Registered
                </h2>
                <p className="mt-1 text-xs text-aegis-text-muted max-w-xl">
                  To begin deterministic spending enforcement, configure your first agent identity, spending passport, and allowlisted merchants.
                </p>
              </div>
            </div>
            <Link
              href="/onboarding"
              className="inline-flex items-center gap-2 border border-aegis-accent bg-aegis-accent px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover transition-colors"
            >
              <span>RUN SETUP WIZARD</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      )}

      {/* Metrics Grid */}
      {loading && !metrics ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 font-mono">
          {[1, 2, 3, 4].map((idx) => (
            <div key={idx} className="h-28 animate-pulse border border-aegis-border bg-aegis-surface p-5" />
          ))}
        </div>
      ) : metrics ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 font-mono">
            {/* Card 1: Budget */}
            <div className="border border-aegis-border bg-aegis-surface p-5 rounded-sm relative">
              <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-aegis-text-muted">
                <span>PASSPORT LIQUIDITY</span>
                <Wallet className="h-3.5 w-3.5 text-aegis-accent" />
              </div>
              <div className="mt-3 text-2xl font-bold text-aegis-text-primary tabular-nums tracking-tight">
                {formatMinorCurrency(metrics.budget.available_minor)}
              </div>
              <div className="mt-2.5 flex items-center justify-between border-t border-aegis-border-subtle pt-2 text-[11px] text-aegis-text-faint">
                <span>
                  SPENT: <span className="text-aegis-copper tabular-nums">{formatMinorCurrency(metrics.budget.spent_minor)}</span>
                </span>
                <span>
                  RESERVED: <span className="text-aegis-text-muted tabular-nums">{formatMinorCurrency(metrics.budget.reserved_minor)}</span>
                </span>
              </div>
            </div>

            {/* Card 2: AI Agents */}
            <div className="border border-aegis-border bg-aegis-surface p-5 rounded-sm relative">
              <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-aegis-text-muted">
                <span>ACTIVE AGENTS</span>
                <Bot className="h-3.5 w-3.5 text-aegis-text-primary" />
              </div>
              <div className="mt-3 text-2xl font-bold text-aegis-text-primary tabular-nums tracking-tight">
                {metrics.agents.active} <span className="text-sm font-normal text-aegis-text-faint">/ {metrics.agents.total}</span>
              </div>
              <div className="mt-2.5 flex items-center justify-between border-t border-aegis-border-subtle pt-2 text-[11px] text-aegis-text-faint">
                <span>HUMAN GATES:</span>
                <Link
                  href="/payments"
                  className={`tabular-nums font-semibold hover:underline ${
                    metrics.pending_approvals > 0 ? "text-aegis-copper" : "text-aegis-accent"
                  }`}
                >
                  {metrics.pending_approvals} PENDING
                </Link>
              </div>
            </div>

            {/* Card 3: Payments & Disputes */}
            <div className="border border-aegis-border bg-aegis-surface p-5 rounded-sm relative">
              <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-aegis-text-muted">
                <span>SETTLEMENT VOLUME</span>
                <Scale className="h-3.5 w-3.5 text-aegis-copper" />
              </div>
              <div className="mt-3 text-2xl font-bold text-aegis-text-primary tabular-nums tracking-tight">
                {metrics.payments.total} <span className="text-sm font-normal text-aegis-text-faint">TXNS</span>
              </div>
              <div className="mt-2.5 flex items-center justify-between border-t border-aegis-border-subtle pt-2 text-[11px] text-aegis-text-faint">
                <span>
                  SETTLED: <span className="text-aegis-accent tabular-nums">{metrics.payments.by_state.SUCCEEDED ?? 0}</span>
                </span>
                <span>
                  DISPUTES: <span className={metrics.open_disputes > 0 ? "text-[#EF5350]" : "text-aegis-text-muted"}>{metrics.open_disputes}</span>
                </span>
              </div>
            </div>

            {/* Card 4: Integrity & Outbox */}
            <div className="border border-aegis-border bg-aegis-surface p-5 rounded-sm relative">
              <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-aegis-text-muted">
                <span>INTEGRITY & OUTBOX</span>
                {metrics.risk_alerts > 0 ? (
                  <AlertTriangle className="h-3.5 w-3.5 text-[#EF5350]" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5 text-aegis-accent" />
                )}
              </div>
              <div className="mt-3 text-2xl font-bold tabular-nums tracking-tight">
                {metrics.risk_alerts > 0 ? (
                  <span className="text-[#EF5350]">{metrics.risk_alerts} ALERTS</span>
                ) : (
                  <span className="text-aegis-accent">VERIFIED</span>
                )}
              </div>
              <div className="mt-2.5 flex items-center justify-between border-t border-aegis-border-subtle pt-2 text-[11px] text-aegis-text-faint">
                <span>DEAD-LETTER OUTBOX:</span>
                <span className={`tabular-nums font-semibold ${metrics.dead_letter_outbox > 0 ? "text-[#EF5350]" : "text-aegis-text-muted"}`}>
                  {metrics.dead_letter_outbox}
                </span>
              </div>
            </div>
          </div>

          {/* Recent Chained Financial Events Section */}
          <section className="mt-10">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-aegis-accent" />
                <h2 id="recent-events-caption" className="text-sm font-semibold tracking-tight text-aegis-text-primary">
                  Tamper-Evident Financial Event Stream
                </h2>
                <span className="border border-aegis-border bg-aegis-card px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-aegis-text-faint">
                  HMAC-SHA256
                </span>
              </div>
              <Link
                href="/audit"
                className="font-mono text-xs text-aegis-accent hover:text-aegis-accent-hover transition-colors flex items-center gap-1"
              >
                <span>VERIFY COMPLETE HASH-CHAIN</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>

            {metrics.recent_events.length === 0 ? (
              <div className="border border-dashed border-aegis-border bg-aegis-surface p-8 text-center font-mono text-xs text-aegis-text-muted">
                NO FINANCIAL EVENTS RECORDED YET. INITIALIZE AN AGENT OR RUN GHOSTPAY REPLAY TO GENERATE ATOMIC AUDIT EVENTS.
              </div>
            ) : (
              <div tabIndex={0} role="region" aria-labelledby="recent-events-caption" className="table-wrapper">
                <table className="aegis-table">
                  <thead>
                    <tr>
                      <th scope="col">SEQ #</th>
                      <th scope="col">EVENT IDENTIFIER</th>
                      <th scope="col">ACTOR / AGENT</th>
                      <th scope="col">PREVIOUS BLOCK HASH</th>
                      <th scope="col">EVENT INTEGRITY HASH</th>
                      <th scope="col">CHRONO TIMESTAMP</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.recent_events.map((evt) => (
                      <tr key={evt.id}>
                        <td className="font-mono text-xs tabular-nums text-aegis-text-muted font-semibold">
                          #{String(evt.sequence_number).padStart(4, "0")}
                        </td>
                        <td>
                          <span className="font-mono text-xs font-semibold text-aegis-text-primary">
                            {evt.event_type}
                          </span>
                        </td>
                        <td className="font-mono text-xs text-aegis-text-muted">
                          <span className="text-aegis-text-faint">{evt.actor_type}:</span> {truncateId(evt.actor_id, 10)}
                        </td>
                        <td className="font-mono text-xs text-aegis-text-faint">
                          {evt.previous_event_hash ? (
                            <span className="text-aegis-text-muted">{truncateId(evt.previous_event_hash, 12)}</span>
                          ) : (
                            <span className="border border-aegis-border px-1 py-0.5 text-[10px] text-aegis-copper uppercase">
                              GENESIS
                            </span>
                          )}
                        </td>
                        <td className="font-mono text-xs text-aegis-accent font-semibold">
                          {truncateId(evt.event_hash, 12)}
                        </td>
                        <td className="font-mono text-xs text-aegis-text-muted tabular-nums">
                          {formatIsoDateTime(evt.occurred_at)}
                        </td>
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
