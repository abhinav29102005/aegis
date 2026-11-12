"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiRequest, type FinancialEventRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, truncateId } from "@/lib/format";
import { CheckCircle2, AlertTriangle } from "lucide-react";

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
      title="Tamper-Evident Audit Ledger"
      subtitle="Verify SHA-256 financial event hash chains per correlation ID and inspect administrative RBAC operations."
    >
      {error && (
        <div role="alert" className="mb-4 border border-[#4A2828] bg-[#211212] p-3 font-mono text-xs text-[#EF5350]">
          {error}
        </div>
      )}

      {/* Cryptographic Hash Chain Verification & Filters Banner */}
      <section className="mb-6 border border-aegis-border bg-aegis-surface p-5 rounded-sm">
        <div className="flex flex-wrap items-center justify-between gap-4 font-mono text-xs">
          <div className="flex flex-1 flex-wrap items-center gap-3">
            {/* Correlation ID Filter */}
            <div className="flex min-w-[280px] flex-1 items-center gap-2">
              <label htmlFor="correlation-filter" className="uppercase text-aegis-text-muted text-[10px]">
                CORRELATION ID:
              </label>
              <input
                id="correlation-filter"
                type="text"
                value={correlationFilter}
                onChange={(e) => {
                  setCorrelationFilter(e.target.value);
                  setPage(1);
                }}
                placeholder="Paste UUID to verify hash chain..."
                className="flex-1 border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
              {correlationFilter && (
                <button
                  type="button"
                  onClick={() => {
                    setCorrelationFilter("");
                    setPage(1);
                  }}
                  className="border border-aegis-border bg-aegis-card px-2.5 py-1.5 text-xs text-aegis-text-muted hover:text-aegis-text-primary"
                >
                  CLEAR
                </button>
              )}
            </div>

            {/* Event Type Filter */}
            <div className="flex items-center gap-2">
              <label htmlFor="event-type-filter" className="uppercase text-aegis-text-muted text-[10px]">
                EVENT TYPE:
              </label>
              <select
                id="event-type-filter"
                aria-label="Filter by event type"
                value={eventTypeFilter}
                onChange={(e) => {
                  setEventTypeFilter(e.target.value);
                  setPage(1);
                }}
                className="border border-aegis-border bg-aegis-card px-2.5 py-1.5 text-xs text-aegis-text-primary focus:outline-none"
              >
                <option value="">ALL EVENT TYPES</option>
                {COMMON_EVENT_TYPES.map((et) => (
                  <option key={et} value={et} className="bg-aegis-surface">
                    {et}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Verification Status Badge */}
          <div>
            {chainVerified === true && (
              <div className="flex items-center gap-2 border border-[#3A4A28] bg-[#162112] px-3 py-1.5 font-bold text-aegis-accent uppercase tracking-wider text-[11px]">
                <CheckCircle2 className="h-4 w-4 text-aegis-accent" />
                <span>HMAC-SHA256 CHAIN AUTHENTICATED (0 TAMPERING)</span>
              </div>
            )}
            {chainVerified === false && (
              <div className="flex items-center gap-2 border border-[#4A2828] bg-[#211212] px-3 py-1.5 font-bold text-[#EF5350] uppercase tracking-wider text-[11px]">
                <AlertTriangle className="h-4 w-4 text-[#EF5350] animate-pulse" />
                <span>INTEGRITY FAILURE: HASH-CHAIN BROKEN</span>
              </div>
            )}
            {chainVerified === null && (
              <span className="text-[11px] text-aegis-text-faint">
                FILTER BY CORRELATION ID TO VERIFY MONOTONIC SEQUENCE CHAIN
              </span>
            )}
          </div>
        </div>

        {chainErrors.length > 0 && (
          <div className="mt-3 border border-[#4A2828] bg-[#211212] p-3 font-mono text-xs text-[#EF5350]">
            <strong className="uppercase tracking-wider">Chain verification anomalies detected:</strong>
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
        <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-3 mb-4">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-text-faint">
                FINANCIAL EVENT LOG
              </span>
              <h2 className="text-sm font-semibold text-aegis-text-primary">Financial Ledger Events ({eventCount})</h2>
            </div>
            <div className="flex items-center gap-2 font-mono text-xs text-aegis-text-muted">
              <span>LIMIT:</span>
              <select
                aria-label="Events per page limit"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="border border-aegis-border bg-aegis-card px-2 py-0.5 text-xs text-aegis-text-primary focus:outline-none"
              >
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </div>
          </div>

          <div tabIndex={0} role="region" aria-label="Hash-chained financial events" className="table-wrapper">
            <table className="aegis-table">
              <caption className="sr-only">Hash-chained financial events</caption>
              <thead>
                <tr>
                  <th scope="col">SEQ</th>
                  <th scope="col">EVENT</th>
                  <th scope="col">CORRELATION</th>
                  <th scope="col">PREVIOUS HASH</th>
                  <th scope="col">EVENT HASH</th>
                  <th scope="col">STATUS</th>
                  <th scope="col">TIMESTAMP</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={7} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                      LOADING LEDGER STREAM…
                    </td>
                  </tr>
                ) : events.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                      NO FINANCIAL EVENTS MATCH APPLIED CRITERIA.
                    </td>
                  </tr>
                ) : (
                  events.map((ev) => (
                    <tr key={ev.id}>
                      <td className="font-mono text-xs text-aegis-text-muted tabular-nums">#{ev.sequence_number}</td>
                      <td className="font-mono text-xs font-semibold text-aegis-text-primary">{ev.event_type}</td>
                      <td className="font-mono text-xs">
                        <button
                          type="button"
                          onClick={() => {
                            setCorrelationFilter(ev.correlation_id);
                            setPage(1);
                          }}
                          title="Click to verify this correlation hash chain"
                          className="text-aegis-accent hover:underline"
                        >
                          {truncateId(ev.correlation_id, 10)}
                        </button>
                      </td>
                      <td className="font-mono text-xs text-aegis-text-faint">
                        {ev.previous_event_hash ? (
                          truncateId(ev.previous_event_hash, 10)
                        ) : (
                          <span className="border border-aegis-border px-1 py-0.5 text-[9px] text-aegis-copper uppercase">
                            GENESIS
                          </span>
                        )}
                      </td>
                      <td className="font-mono text-xs text-aegis-accent font-semibold" title={ev.event_hash}>
                        {truncateId(ev.event_hash, 10)}
                      </td>
                      <td>
                        {chainVerified === true ? (
                          <span className="text-aegis-accent font-bold text-[11px]" title="Chain hash authenticated">
                            ✓
                          </span>
                        ) : chainVerified === false ? (
                          <span className="text-[#EF5350] font-bold text-[11px]" title="Chain integrity broken">
                            ✗
                          </span>
                        ) : (
                          <span className="text-aegis-text-faint text-[11px]">⛓</span>
                        )}
                      </td>
                      <td className="font-mono text-xs text-aegis-text-muted tabular-nums">
                        {formatIsoDateTime(ev.occurred_at)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination controls for financial events */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-aegis-border pt-3 font-mono text-xs text-aegis-text-faint mt-4">
            <span>
              PAGE {page} {eventCount > 0 ? `(${events.length} SHOWN)` : ""}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
              >
                PREV
              </button>
              <button
                type="button"
                disabled={!hasMore}
                onClick={() => setPage((p) => p + 1)}
                className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
              >
                NEXT
              </button>
            </div>
          </div>
        </section>

        {/* Administrative Security & Governance Logs Table */}
        <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
          <div className="border-b border-aegis-border pb-3 mb-4">
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-text-faint">
              RBAC & SECURITY AUDIT
            </span>
            <h2 className="text-sm font-semibold text-aegis-text-primary">
              Administrative & Governance Logs ({adminAudits.length})
            </h2>
          </div>

          <div tabIndex={0} role="region" aria-label="Organization administrative audit logs" className="table-wrapper">
            <table className="aegis-table">
              <caption className="sr-only">Organization administrative audit logs</caption>
              <thead>
                <tr>
                  <th scope="col">ACTION</th>
                  <th scope="col">ACTOR</th>
                  <th scope="col">RESOURCE</th>
                  <th scope="col">TIMESTAMP</th>
                </tr>
              </thead>
              <tbody>
                {adminAudits.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                      NO ADMINISTRATIVE AUDIT LOGS RECORDED.
                    </td>
                  </tr>
                ) : (
                  adminAudits.map((row) => (
                    <tr key={row.id}>
                      <td className="font-mono text-xs font-semibold text-aegis-text-primary">{row.action}</td>
                      <td className="font-mono text-xs text-aegis-text-muted">{row.actor_id}</td>
                      <td className="font-mono text-xs text-aegis-text-faint">
                        {row.resource_type}:{truncateId(row.resource_id, 8)}
                      </td>
                      <td className="font-mono text-xs text-aegis-text-muted tabular-nums">
                        {formatIsoDateTime(row.occurred_at)}
                      </td>
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
