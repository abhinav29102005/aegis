"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type ReplayResultRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, truncateId } from "@/lib/format";

export default function GhostPayReplayDetailPage() {
  const params = useParams<{ id: string }>();
  const paymentIntentId = params?.id ?? "";
  const { session, hasPermission } = useAuth();

  const [replay, setReplay] = useState<ReplayResultRecord | null>(null);
  const [simulation, setSimulation] = useState<ReplayResultRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [perTxUsd, setPerTxUsd] = useState("50.00");
  const [humanThresholdUsd, setHumanThresholdUsd] = useState("25.00");
  const [allowUnknownMerchants, setAllowUnknownMerchants] = useState(false);

  const runReplay = useCallback(async () => {
    if (!session || !paymentIntentId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest<ReplayResultRecord>(`/v1/ghostpay/replay/by-payment/${paymentIntentId}`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {},
      });
      setReplay(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run deterministic replay");
    } finally {
      setLoading(false);
    }
  }, [paymentIntentId, session]);

  useEffect(() => {
    void runReplay();
  }, [runReplay]);

  async function handleRunSimulation(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !paymentIntentId) return;
    setError(null);
    const perTx = Math.round(Number(perTxUsd) * 100);
    const threshold = Math.round(Number(humanThresholdUsd) * 100);
    if (!Number.isFinite(perTx) || perTx <= 0 || !Number.isFinite(threshold) || threshold < 0) {
      setError("Enter valid non-negative USD limits for counterfactual simulation.");
      return;
    }
    setSimulating(true);
    try {
      const sim = await apiRequest<ReplayResultRecord>(`/v1/ghostpay/simulate/by-payment/${paymentIntentId}`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          overrides: {
            per_tx_limit_minor: perTx,
            human_approval_threshold_minor: threshold,
            allow_unknown_merchants: allowUnknownMerchants,
          },
          persist_investigation: true,
        },
      });
      setSimulation(sim);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to execute counterfactual simulation");
    } finally {
      setSimulating(false);
    }
  }

  return (
    <AppShell
      title="Deterministic Replay & Counterfactual Lab"
      subtitle={`Payment Intent ${paymentIntentId}`}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 font-mono text-xs">
        <Link href="/ghostpay" className="text-aegis-accent hover:underline">
          ← Back to GhostPay Investigations
        </Link>
        <Link href={`/payments/${paymentIntentId}`} className="text-aegis-text-muted hover:text-aegis-text-primary hover:underline">
          Inspect Live Payment Lifecycle →
        </Link>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded border border-aegis-rose/40 bg-aegis-rose/10 px-4 py-3 font-mono text-xs text-aegis-rose">
          [FAULT] {error}
        </div>
      )}

      {loading || !replay ? (
        <div className="rounded-xl border border-aegis-border bg-aegis-surface p-6 font-mono text-xs text-aegis-text-muted">
          Running deterministic replay and hash-chain verification…
        </div>
      ) : (
        <div className="space-y-6">
          {/* Replay Result */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge label={replay.consistency_status} />
                <StatusBadge label={replay.integrity_valid ? "VERIFIED" : "INTEGRITY_FAILURE"} />
                <span className="rounded border border-aegis-accent/40 bg-aegis-card px-2 py-0.5 font-mono text-xs text-aegis-accent">
                  executed_payment={String(replay.executed_payment)}
                </span>
              </div>
              <span className="font-mono text-xs text-aegis-text-muted">Policy Engine: {replay.policy_version}</span>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded border border-aegis-border bg-aegis-card p-4">
                <div className="font-mono text-xs uppercase tracking-wider text-aegis-text-muted">Recorded Original Decision</div>
                <div className="mt-2 flex items-center gap-2">
                  <StatusBadge label={replay.original_outcome} />
                  <span className="font-mono text-xs text-aegis-text-muted">{replay.original_reason_codes.join(", ") || "—"}</span>
                </div>
              </div>
              <div className="rounded border border-aegis-border bg-aegis-card p-4">
                <div className="font-mono text-xs uppercase tracking-wider text-aegis-text-muted">Recomputed Policy Decision</div>
                <div className="mt-2 flex items-center gap-2">
                  <StatusBadge label={replay.recomputed_outcome} />
                  <span className="font-mono text-xs text-aegis-text-muted">{replay.recomputed_reason_codes.join(", ") || "—"}</span>
                </div>
              </div>
            </div>

            <p className="mt-4 text-xs text-aegis-text-primary leading-relaxed">{replay.explanation}</p>

            {replay.anomalies.length > 0 && (
              <div className="mt-3 rounded border border-aegis-copper/40 bg-aegis-card p-3 font-mono text-xs text-aegis-copper">
                Detected anomalies: {replay.anomalies.join(", ")}
              </div>
            )}
            {replay.missing_evidence.length > 0 && (
              <div className="mt-3 rounded border border-aegis-rose/40 bg-aegis-card p-3 font-mono text-xs text-aegis-rose">
                Missing evidence: {replay.missing_evidence.join(", ")}
              </div>
            )}
          </section>

          {/* Counterfactual Simulator */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="border-b border-aegis-border pb-3">
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper">[SIMULATION // WHAT-IF]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Counterfactual Policy Simulation</h2>
            </div>
            <p className="mt-2 text-xs text-aegis-text-muted">
              Test what deterministic verdict the policy engine would produce under hypothetical thresholds without modifying stored ledger balances.
            </p>
            <form onSubmit={handleRunSimulation} className="mt-4 grid gap-4 md:grid-cols-4 font-mono text-xs">
              <div>
                <label htmlFor="sim-per-tx" className="block text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Per-Tx Limit (USD)
                </label>
                <input
                  id="sim-per-tx"
                  type="number"
                  step="0.01"
                  value={perTxUsd}
                  onChange={(e) => setPerTxUsd(e.target.value)}
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="sim-threshold" className="block text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Escalation Threshold (USD)
                </label>
                <input
                  id="sim-threshold"
                  type="number"
                  step="0.01"
                  value={humanThresholdUsd}
                  onChange={(e) => setHumanThresholdUsd(e.target.value)}
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-xs text-aegis-text-primary">
                  <input
                    type="checkbox"
                    checked={allowUnknownMerchants}
                    onChange={(e) => setAllowUnknownMerchants(e.target.checked)}
                    className="rounded border-aegis-border bg-aegis-card text-aegis-accent focus:ring-aegis-accent"
                  />
                  Allow unknown merchants
                </label>
              </div>
              <div className="flex items-end">
                <button
                  type="submit"
                  disabled={simulating || !hasPermission("ghostpay:simulate")}
                  className="w-full rounded bg-aegis-accent px-4 py-2 font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] disabled:opacity-50 transition"
                >
                  {simulating ? "Simulating…" : "Run Counterfactual"}
                </button>
              </div>
            </form>

            {simulation && (
              <div className="mt-4 rounded border border-aegis-accent/40 bg-aegis-card p-4 text-xs font-mono">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-aegis-accent uppercase tracking-wider">Counterfactual Verdict</span>
                  <div className="flex items-center gap-2">
                    <StatusBadge label={simulation.original_outcome} />
                    <span className="text-aegis-text-muted">→</span>
                    <StatusBadge label={simulation.recomputed_outcome} />
                  </div>
                </div>
                <p className="mt-2 text-aegis-text-primary">{simulation.explanation}</p>
                {simulation.changed_constraints.length > 0 && (
                  <p className="mt-1 text-[11px] text-aegis-accent">
                    Constraint deltas: {simulation.changed_constraints.join(", ")}
                  </p>
                )}
              </div>
            )}
          </section>

          {/* Forensic Timeline */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="border-b border-aegis-border px-5 py-3">
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[PROVENANCE // TIMELINE]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">
                Tamper-Evident History ({replay.timeline.length} events)
              </h2>
            </div>
            <div className="divide-y divide-aegis-border">
              {replay.timeline.map((entry) => (
                <div key={`${entry.sequence_number}-${entry.event_type}`} className="flex flex-wrap items-start justify-between gap-2 px-5 py-3 text-xs">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-aegis-accent font-bold">#{entry.sequence_number}</span>
                      <span className="font-semibold text-aegis-text-primary">{entry.event_type}</span>
                      <span className="rounded border border-aegis-border bg-aegis-card px-1.5 py-0.5 font-mono text-[11px] text-aegis-text-muted">
                        {entry.actor_type}: {entry.actor_id}
                      </span>
                      {entry.integrity_verified !== undefined && (
                        <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium ${entry.integrity_verified
                            ? "border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent"
                            : "border-aegis-rose/40 bg-aegis-rose/15 text-aegis-rose"
                          }`}>
                          {entry.integrity_verified ? "✓ Verified" : "✗ Integrity Fail"}
                        </span>
                      )}
                    </div>
                    <p className="text-aegis-text-muted">{entry.summary}</p>
                    <div className="flex flex-wrap items-center gap-4 font-mono text-[11px] text-aegis-text-faint">
                      <span>Hash: <span className="text-aegis-accent">{truncateId(entry.event_hash, 12)}</span></span>
                      <span>Prev: <span className="text-aegis-text-muted">{entry.previous_event_hash ? truncateId(entry.previous_event_hash, 12) : "GENESIS"}</span></span>
                    </div>
                  </div>
                  <span className="font-mono text-[11px] text-aegis-text-faint">{formatIsoDateTime(entry.occurred_at)}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </AppShell>
  );
}