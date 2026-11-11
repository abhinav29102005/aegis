"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type ReplayResultRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime } from "@/lib/format";

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
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Link href="/ghostpay" className="text-xs font-medium text-sky-400 hover:underline">
          ← Back to GhostPay Investigations
        </Link>
        <Link href={`/payments/${paymentIntentId}`} className="text-xs font-medium text-slate-300 hover:underline">
          Inspect Live Payment Lifecycle →
        </Link>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {loading || !replay ? (
        <div className="rounded-xl border border-aegis-border bg-aegis-surface p-6 text-sm text-slate-400">
          Running deterministic replay and hash-chain verification…
        </div>
      ) : (
        <div className="space-y-6">
          {/* Replay Result */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge label={replay.consistency_status} />
                <StatusBadge label={replay.integrity_valid ? "VERIFIED" : "INTEGRITY_FAILURE"} />
                <span className="rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 font-mono text-xs text-sky-300">
                  executed_payment={String(replay.executed_payment)}
                </span>
              </div>
              <span className="font-mono text-xs text-slate-400">Policy {replay.policy_version}</span>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded-lg border border-aegis-border bg-aegis-panel p-4">
                <div className="text-xs uppercase text-slate-400">Recorded Original Decision</div>
                <div className="mt-2 flex items-center gap-2">
                  <StatusBadge label={replay.original_outcome} />
                  <span className="text-xs text-slate-300">{replay.original_reason_codes.join(", ") || "—"}</span>
                </div>
              </div>
              <div className="rounded-lg border border-aegis-border bg-aegis-panel p-4">
                <div className="text-xs uppercase text-slate-400">Recomputed Policy Decision</div>
                <div className="mt-2 flex items-center gap-2">
                  <StatusBadge label={replay.recomputed_outcome} />
                  <span className="text-xs text-slate-300">{replay.recomputed_reason_codes.join(", ") || "—"}</span>
                </div>
              </div>
            </div>

            <p className="mt-4 text-sm text-slate-200">{replay.explanation}</p>

            {replay.anomalies.length > 0 && (
              <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
                Detected anomalies: {replay.anomalies.join(", ")}
              </div>
            )}
            {replay.missing_evidence.length > 0 && (
              <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                Missing evidence: {replay.missing_evidence.join(", ")}
              </div>
            )}
          </section>

          {/* Counterfactual Simulator */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <h2 className="text-sm font-semibold text-white">Counterfactual Policy Simulation</h2>
            <p className="mt-0.5 text-xs text-slate-400">
              Test what deterministic verdict the policy engine would produce under modified thresholds without altering stored ledger balances.
            </p>
            <form onSubmit={handleRunSimulation} className="mt-4 grid gap-4 md:grid-cols-4">
              <div>
                <label htmlFor="sim-per-tx" className="block text-xs font-medium text-slate-300">
                  Per-Tx Limit (USD)
                </label>
                <input
                  id="sim-per-tx"
                  type="number"
                  step="0.01"
                  value={perTxUsd}
                  onChange={(e) => setPerTxUsd(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label htmlFor="sim-threshold" className="block text-xs font-medium text-slate-300">
                  Human Approval Threshold (USD)
                </label>
                <input
                  id="sim-threshold"
                  type="number"
                  step="0.01"
                  value={humanThresholdUsd}
                  onChange={(e) => setHumanThresholdUsd(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-xs text-slate-200">
                  <input
                    type="checkbox"
                    checked={allowUnknownMerchants}
                    onChange={(e) => setAllowUnknownMerchants(e.target.checked)}
                    className="rounded border-aegis-border bg-aegis-panel"
                  />
                  Allow unknown merchants
                </label>
              </div>
              <div className="flex items-end">
                <button
                  type="submit"
                  disabled={simulating || !hasPermission("ghostpay:simulate")}
                  className="w-full rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                >
                  {simulating ? "Simulating…" : "Run Counterfactual"}
                </button>
              </div>
            </form>

            {simulation && (
              <div className="mt-4 rounded-lg border border-sky-500/30 bg-sky-500/10 p-4 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-sky-200">Counterfactual Result</span>
                  <div className="flex items-center gap-2">
                    <StatusBadge label={simulation.original_outcome} />
                    <span className="text-slate-300">→</span>
                    <StatusBadge label={simulation.recomputed_outcome} />
                  </div>
                </div>
                <p className="mt-2 text-slate-200">{simulation.explanation}</p>
                {simulation.changed_constraints.length > 0 && (
                  <p className="mt-1 font-mono text-[11px] text-sky-300">
                    Changed constraints: {simulation.changed_constraints.join(", ")}
                  </p>
                )}
              </div>
            )}
          </section>

          {/* Forensic Timeline */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="border-b border-aegis-border px-5 py-3">
              <h2 className="text-sm font-semibold text-white">Provenance Timeline ({replay.timeline.length})</h2>
            </div>
            <div className="divide-y divide-aegis-border">
              {replay.timeline.map((entry) => (
                <div key={`${entry.sequence_number}-${entry.event_type}`} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-xs">
                  <div>
                    <span className="font-mono text-slate-400">#{entry.sequence_number}</span>{" "}
                    <span className="font-semibold text-white">{entry.event_type}</span>{" "}
                    <span className="text-slate-400">({entry.source} · {entry.actor})</span>
                    <p className="mt-0.5 text-slate-300">{entry.summary}</p>
                  </div>
                  <span className="font-mono text-[11px] text-slate-400">{formatIsoDateTime(entry.timestamp)}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </AppShell>
  );
}
