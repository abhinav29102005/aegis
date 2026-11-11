"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
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

const COMMON_EVENT_TYPES = [
  "PAYMENT_PROPOSED",
  "POLICY_EVALUATED",
  "APPROVAL_REQUESTED",
  "APPROVAL_GRANTED",
  "APPROVAL_REJECTED",
  "CHECKOUT_CREATED",
  "CAPTURE_PENDING",
  "CAPTURE_VERIFIED",
  "PAYMENT_SUCCEEDED",
  "PAYMENT_FAILED",
  "DISPUTE_OPENED",
  "DISPUTE_EVIDENCE_ATTACHED",
  "DISPUTE_ANALYZED",
  "DISPUTE_APPROVED",
  "DISPUTE_SUBMITTED",
  "DISPUTE_RESOLVED",
];

export default function AuditLogPage() {
  const { session } = useAuth();

  // Filters & Pagination state
  const [correlationFilter, setCorrelationFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Data state
  const [events, setEvents] = useState<FinancialEventRecord[]>([]);
  const [eventCount, setEventCount] = useState(0);
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
      const offset = (page - 1) * pageSize;
      const qs = new URLSearchParams({
        limit: String(pageSize),
        offset: String(offset),
      });
      if (correlationFilter.trim()) {
        qs.set("correlation_id", correlationFilter.trim());
      }
      if (eventTypeFilter.trim()) {
        qs.set("event_type", eventTypeFilter.trim());
      }

      const [finResp, admResp] = await Promise.all([
        apiRequest<{
          items: FinancialEventRecord[];
          count: number;
          limit: number;
          offset: number;
          chain_verified: boolean | null;
          chain_errors: string[];
        }>(`/v1/audit-events?${qs.toString()}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<{ items: AdminAuditItem[] }>("/v1/orgs/audit-logs?limit=50", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }).catch(() => ({ items: [] as AdminAuditItem[] })),
      ]);

      setEvents(finResp.items || []);
      setEventCount(finResp.count ?? (finResp.items ? finResp.items.length : 0));
      setChainVerified(finResp.chain_verified);
      setChainErrors(finResp.chain_errors ?? []);
      setAdminAudits(admResp.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit logs");
    } finally {
      setLoading(false);
    }
  }, [correlationFilter, eventTypeFilter, page, pageSize, session]);

  useEffect(() => {
    void loadAudits();
  }, [loadAudits]);

  const hasMore = events.length === pageSize;

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

      {/* Cryptographic Hash Chain Verification & Filters Banner */}
      <section className="mb-6 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-1 flex-wrap items-center gap-3">
            {/* Correlation ID Filter */}
            <div className="flex min-w-[280px] flex-1 items-center gap-2">
              <label htmlFor="correlation-filter" className="text-xs font-medium text-slate-300">
                Correlation ID:
              </label>
              <input
                id="correlation-filter"
                type="text"
                value={correlationFilter}
                onChange={(e) => {
                  setCorrelationFilter(e.target.value);
                  setPage(1);
                }}
                placeholder="Paste or click any correlation UUID to verify hash chain..."
                className="flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 font-mono text-xs text-white placeholder-slate-500"
              />
              {correlationFilter && (
                <button
                  type="button"
                  onClick={() => {
                    setCorrelationFilter("");
                    setPage(1);
                  }}
                  className="rounded-lg border border-aegis-border px-2.5 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Clear
                </button>
              )}
            </div>

            {/* Event Type Filter */}
            <div className="flex items-center gap-2 text-xs">
              <label htmlFor="event-type-filter" className="font-medium text-slate-300">
                Event Type:
              </label>
              <select
                id="event-type-filter"
                aria-label="Filter by event type"
                value={eventTypeFilter}
                onChange={(e) => {
                  setEventTypeFilter(e.target.value);
                  setPage(1);
                }}
                className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1.5 text-xs text-white"
              >
                <option value="">All Event Types</option>
                {COMMON_EVENT_TYPES.map((et) => (
                  <option key={et} value={et}>
                    {et}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Verification Status Badge */}
          <div>
            {chainVerified === true && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400" />
                <span>SHA-256 Chain Verified (0 Tampering)</span>
              </div>
            )}
            {chainVerified === false && (
              <div className="flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-1.5 text-xs font-semibold text-rose-300">
                <span className="h-2 w-2 rounded-full bg-rose-400 animate-pulse" />
                <span>INTEGRITY FAILURE: Chain Broken</span>
              </div>
            )}
            {chainVerified === null && (
              <span className="text-xs text-slate-400">
                Filter by Correlation ID to verify cryptographic chain integrity
              </span>
            )}
          </div>
        </div>

        {chainErrors.length > 0 && (
          <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
            <strong>Chain verification failures detected:</strong>
            <ul className="mt-1 list-inside list-disc space-y-0.5">
              {chainErrors.map((errStr, idx) => (
                <li key={idx}>{errStr}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Main Audit Tables Grid */}
      <div className="grid gap-6 xl:grid-cols-2">
        {/* Financial Ledger Events Table */}
        <section className="rounded-xl border border-aegis-border bg-aegis-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border px-5 py-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-white">Financial Ledger Events</h2>
              <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
                {eventCount} items
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span>Limit:</span>
              <select
                aria-label="Events per page limit"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="rounded border border-aegis-border bg-aegis-panel px-2 py-0.5 text-xs text-white"
              >
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Hash-chained financial events</caption>
              <thead className="border-b border-aegis-border bg-aegis-panel/60 uppercase text-slate-400">
                <tr>
                  <th scope="col" className="px-3 py-2.5">Seq</th>
                  <th scope="col" className="px-3 py-2.5">Event</th>
                  <th scope="col" className="px-3 py-2.5">Correlation</th>
                  <th scope="col" className="px-3 py-2.5">Previous Hash</th>
                  <th scope="col" className="px-3 py-2.5">Event Hash</th>
                  <th scope="col" className="px-3 py-2.5">Chain</th>
                  <th scope="col" className="px-3 py-2.5">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-aegis-border">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                      Loading financial events…
                    </td>
                  </tr>
                ) : events.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                      No financial events matched the filter criteria.
                    </td>
                  </tr>
                ) : (
                  events.map((ev) => (
                    <tr key={ev.id} className="hover:bg-slate-800/30">
                      <td className="px-3 py-2.5 font-mono text-slate-400">#{ev.sequence_number}</td>
                      <td className="px-3 py-2.5 font-medium text-white">{ev.event_type}</td>
                      <td className="px-3 py-2.5 font-mono">
                        <button
                          type="button"
                          onClick={() => {
                            setCorrelationFilter(ev.correlation_id);
                            setPage(1);
                          }}
                          title="Click to verify this correlation hash chain"
                          className="text-sky-300 hover:underline"
                        >
                          {truncateId(ev.correlation_id, 10)}
                        </button>
                      </td>
                      <td className="px-3 py-2.5 font-mono">
                        {ev.previous_event_hash ? (
                          <span className="text-slate-400" title={ev.previous_event_hash}>
                            {truncateId(ev.previous_event_hash, 10)}
                          </span>
                        ) : (
                          <span className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-sky-300">
                            GENESIS
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-sky-200" title={ev.event_hash}>
                        {truncateId(ev.event_hash, 10)}
                      </td>
                      <td className="px-3 py-2.5">
                        {chainVerified === true ? (
                          <span className="text-emerald-400 font-semibold text-[11px]" title="Chain hash authenticated">
                            ✓
                          </span>
                        ) : chainVerified === false ? (
                          <span className="text-rose-400 font-semibold text-[11px]" title="Chain integrity broken">
                            ✗
                          </span>
                        ) : (
                          <span className="text-slate-500 text-[11px]">⛓</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-slate-400">{formatIsoDateTime(ev.occurred_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination controls for financial events */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-aegis-border px-5 py-3 text-xs text-slate-400">
            <span>
              Page {page} {eventCount > 0 ? `(${events.length} shown)` : ""}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="rounded border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!hasMore}
                onClick={() => setPage((p) => p + 1)}
                className="rounded border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </section>

        {/* Administrative Security & Governance Logs Table */}
        <section className="rounded-xl border border-aegis-border bg-aegis-surface">
          <div className="border-b border-aegis-border px-5 py-3">
            <h2 className="text-sm font-semibold text-white">
              Administrative Security & Governance Logs ({adminAudits.length})
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">Organization administrative audit logs</caption>
              <thead className="border-b border-aegis-border bg-aegis-panel/60 uppercase text-slate-400">
                <tr>
                  <th scope="col" className="px-4 py-2.5">Action</th>
                  <th scope="col" className="px-4 py-2.5">Actor</th>
                  <th scope="col" className="px-4 py-2.5">Resource</th>
                  <th scope="col" className="px-4 py-2.5">Time</th>
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
