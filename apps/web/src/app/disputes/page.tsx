"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type DisputeCaseRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

export default function DisputesPage() {
  const { session, hasPermission } = useAuth();
  const [cases, setCases] = useState<DisputeCaseRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [syntheticFilter, setSyntheticFilter] = useState<"ALL" | "REAL" | "SYNTHETIC">("ALL");
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadCases = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (statusFilter) qs.set("status_filter", statusFilter);
      if (syntheticFilter === "REAL") qs.set("is_synthetic", "false");
      if (syntheticFilter === "SYNTHETIC") qs.set("is_synthetic", "true");
      const query = qs.toString() ? `?${qs.toString()}` : "";
      const rows = await apiRequest<DisputeCaseRecord[]>(`/v1/disputeos/cases${query}`, {
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setCases(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dispute cases");
    } finally {
      setLoading(false);
    }
  }, [session, statusFilter, syntheticFilter]);

  useEffect(() => {
    void loadCases();
  }, [loadCases]);

  async function handleSeedSyntheticDemo() {
    if (!session) return;
    setSeeding(true);
    setError(null);
    setNotice(null);
    try {
      const res = await apiRequest<{ case: DisputeCaseRecord }>("/v1/disputeos/cases/seed-demo", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setNotice(
        `Seeded synthetic sandbox demo case ${truncateId(res.case.id, 12)} (marked SYNTHETIC_DEMO — non-submittable externally).`,
      );
      await loadCases();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to seed synthetic dispute demo");
    } finally {
      setSeeding(false);
    }
  }

  return (
    <AppShell
      title="DisputeOS Case Center"
      subtitle="Evidence provenance graphs, contradiction detection, grounded AI analysis, and human-approved response submission."
    >
      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mb-4 rounded-xl border border-sky-500/40 bg-sky-500/10 px-4 py-3 text-sm text-sky-200">
          {notice}
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-aegis-border bg-aegis-surface px-5 py-3">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <select
            aria-label="Filter by case status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1.5 text-xs text-white"
          >
            <option value="">All Statuses</option>
            <option value="OPEN">OPEN</option>
            <option value="UNDER_INVESTIGATION">UNDER_INVESTIGATION</option>
            <option value="DRAFT_READY">DRAFT_READY</option>
            <option value="APPROVED_FOR_SUBMISSION">APPROVED_FOR_SUBMISSION</option>
            <option value="SUBMITTED">SUBMITTED</option>
          </select>
          <select
            aria-label="Filter by data origin"
            value={syntheticFilter}
            onChange={(e) => setSyntheticFilter(e.target.value as "ALL" | "REAL" | "SYNTHETIC")}
            className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1.5 text-xs text-white"
          >
            <option value="ALL">All Origins</option>
            <option value="REAL">Production / Live Cases</option>
            <option value="SYNTHETIC">Synthetic Demo Only</option>
          </select>
        </div>

        {hasPermission("disputes:write") && (
          <button
            type="button"
            disabled={seeding}
            onClick={() => void handleSeedSyntheticDemo()}
            className="rounded-lg border border-sky-500/40 bg-sky-500/15 px-3.5 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-500/25 disabled:opacity-50"
          >
            {seeding ? "Seeding Demo Case…" : "Seed Synthetic Demo Case"}
          </button>
        )}
      </div>

      <section className="rounded-xl border border-aegis-border bg-aegis-surface">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Organization dispute cases</caption>
            <thead className="border-b border-aegis-border bg-aegis-panel/60 text-xs uppercase text-slate-400">
              <tr>
                <th className="px-4 py-3">Case ID</th>
                <th className="px-4 py-3">Reason</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Origin</th>
                <th className="px-4 py-3">Evidence</th>
                <th className="px-4 py-3">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-aegis-border">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                    Loading dispute cases…
                  </td>
                </tr>
              ) : cases.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                    No dispute cases recorded for this organization yet.
                  </td>
                </tr>
              ) : (
                cases.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-800/30">
                    <td className="px-4 py-3 font-mono text-xs text-sky-300">
                      <Link href={`/disputes/${c.id}`} className="hover:underline">
                        {truncateId(c.id, 12)}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-xs text-white">{c.reason}</td>
                    <td className="px-4 py-3 text-xs font-medium text-white">
                      {formatMinorCurrency(c.amount_minor, c.currency)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge label={c.status} />
                    </td>
                    <td className="px-4 py-3">
                      {c.is_synthetic ? <StatusBadge label="SYNTHETIC_DEMO" /> : <span className="text-xs text-slate-300">{c.source_type}</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-300">{c.evidence_ids.length} items</td>
                    <td className="px-4 py-3 text-xs text-slate-400">{formatIsoDateTime(c.updated_at)}</td>
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
