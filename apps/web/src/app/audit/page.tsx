"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type FinancialEventRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, truncateId } from "@/lib/format";

interface AdminAuditItem {
  id: string;
  actor_type: string;
  actor_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown>;
  occurred_at: string;
}

export default function AuditLogPage() {
  const { session } = useAuth();
  const [correlationFilter, setCorrelationFilter] = useState("");
  const [events, setEvents] = useState<FinancialEventRecord[]>([]);
  const [chainVerified, setChainVerified] = useState<boolean | null>(null);
  const [chainErrors, setChainErrors] = useState<string[]>([]);
  const [adminAudits, setAdminAudits] = useState<AdminAuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAudits = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ limit: "100" });
      if (correlationFilter.trim()) {
        qs.set("correlation_id", correlationFilter.trim());
      }
      const [finResp, admResp] = await Promise.all([
        apiRequest<{
          items: FinancialEventRecord[];
          chain_verified: boolean | null;
          chain_errors: string[];
        }>(`/v1/audit-events?${qs.toString()}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<{ items: AdminAuditItem[] }>("/v1/orgs/audit-logs?limit=50", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
      ]);
      setEvents(finResp.items);
      setChainVerified(finResp.chain_verified);
      setChainErrors(finResp.chain_errors ?? []);
      setAdminAudits(admResp.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit logs");
    } finally {
      setLoading(false);
    }
  }, [correlationFilter, session]);

  useEffect(() => {
    void loadAudits();
  }, [loadAudits]);

  return (
    <AppShell
      title="Cryptographic Audit Log"
      subtitle="Verify SHA-256 financial event hash chains per correlation ID and inspect administrative RBAC changes."
    >
      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <section className="mb-6 rounded-xl border border-aegis-border bg-aegis-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-1 items-center gap-2">
            <label htmlFor="correlation-filter" className="text-xs font-medium text-slate-300">
              Correlation ID:
            </label>
            <input
              id="correlation-filter"
              type="text"
              value={correlationFilter}
              onChange={(e) => setCorrelationFilter(e.target.value)}
              placeholder="Paste or click any correlation UUID to verify hash chain..."
              className="min-w-[260px] flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 font-mono text-xs text-white"
            />
            {correlationFilter && (
              <button
                type="button"
                onClick={() => setCorrelationFilter("")}
                className="rounded-lg border border-aegis-border px-2.5 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                Clear
              </button>
            )}
          </div>
          <div>
            {chainVerified === true && <StatusBadge label="VERIFIED" />}
            {chainVerified === false && <StatusBadge label="INTEGRITY_FAILURE" />}
            {chainVerified === null && (
              <span className="text-xs text-slate-400">Select a correlation ID to verify chain integrity</span>
            )}
          </div>
        </div>
        {chainErrors.length > 0 && (
          <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
            Chain verification errors: {chainErrors.join("; ")}
          </div>
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="rounded-xl border border-aegis-border bg-aegis-surface">
          <div className="border-b border-aegis-border px-5 py-3">
            <h2 className="text-sm font-semibold text-white">Financial Ledger Events ({events.length})</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Hash-chained financial events</caption>
              <thead className="border-b border-aegis-border bg-aegis-panel/60 uppercase text-slate-400">
                <tr>
                  <th className="px-4 py-2.5">Seq</th>
                  <th className="px-4 py-2.5">Event</th>
                  <th className="px-4 py-2.5">Correlation</th>
                  <th className="px-4 py-2.5">Event Hash</th>
                  <th className="px-4 py-2.5">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-aegis-border">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                      Loading financial events…
                    </td>
                  </tr>
                ) : events.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                      No financial events matched.
                    </td>
                  </tr>
                ) : (
                  events.map((ev) => (
                    <tr key={ev.id} className="hover:bg-slate-800/30">
                      <td className="px-4 py-2.5 font-mono text-slate-400">#{ev.sequence_number}</td>
                      <td className="px-4 py-2.5 font-medium text-white">{ev.event_type}</td>
                      <td className="px-4 py-2.5 font-mono">
                        <button
                          type="button"
                          onClick={() => setCorrelationFilter(ev.correlation_id)}
                          className="text-sky-300 hover:underline"
                        >
                          {truncateId(ev.correlation_id, 10)}
                        </button>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-slate-400">{truncateId(ev.event_hash, 12)}</td>
                      <td className="px-4 py-2.5 text-slate-400">{formatIsoDateTime(ev.occurred_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-xl border border-aegis-border bg-aegis-surface">
          <div className="border-b border-aegis-border px-5 py-3">
            <h2 className="text-sm font-semibold text-white">Administrative Security & Governance Logs ({adminAudits.length})</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Organization administrative audit logs</caption>
              <thead className="border-b border-aegis-border bg-aegis-panel/60 uppercase text-slate-400">
                <tr>
                  <th className="px-4 py-2.5">Action</th>
                  <th className="px-4 py-2.5">Actor</th>
                  <th className="px-4 py-2.5">Resource</th>
                  <th className="px-4 py-2.5">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-aegis-border">
                {adminAudits.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                      No admin audit logs recorded.
                    </td>
                  </tr>
                ) : (
                  adminAudits.map((row) => (
                    <tr key={row.id} className="hover:bg-slate-800/30">
                      <td className="px-4 py-2.5 font-semibold text-white">{row.action}</td>
                      <td className="px-4 py-2.5 text-slate-300">{row.actor_id}</td>
                      <td className="px-4 py-2.5 font-mono text-slate-400">
                        {row.resource_type}:{truncateId(row.resource_id, 8)}
                      </td>
                      <td className="px-4 py-2.5 text-slate-400">{formatIsoDateTime(row.occurred_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
