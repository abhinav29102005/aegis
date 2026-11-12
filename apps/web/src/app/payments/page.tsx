"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import {
  apiRequest,
  type AgentRecord,
  type MerchantRecord,
  type PassportRecord,
  type PaymentIntentRecord,
  type PaymentState,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

// Canonical 11 Payment States
const CANONICAL_PAYMENT_STATES: readonly PaymentState[] = [
  "CREATED",
  "POLICY_CHECK",
  "AWAITING_APPROVAL",
  "APPROVED",
  "CHECKOUT_CREATED",
  "CAPTURE_PENDING",
  "CAPTURED",
  "FAILED",
  "CANCELLED",
  "EXPIRED",
  "REFUNDED",
] as const;

export default function PaymentsPage() {
  const { session, hasPermission } = useAuth();
  const [payments, setPayments] = useState<PaymentIntentRecord[]>([]);
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [passports, setPassports] = useState<PassportRecord[]>([]);
  const [merchants, setMerchants] = useState<MerchantRecord[]>([]);
  const [stateFilter, setStateFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [agentId, setAgentId] = useState("");
  const [passportId, setPassportId] = useState("");
  const [merchantId, setMerchantId] = useState("");
  const [amountUsd, setAmountUsd] = useState("45.00");
  const [currency, setCurrency] = useState("USD");
  const [itemSummary, setItemSummary] = useState("Cloud compute credits");
  const [rationale, setRationale] = useState("Automated agent procurement request");
  const [submitting, setSubmitting] = useState(false);

  const [confirmApprove, setConfirmApprove] = useState<PaymentIntentRecord | null>(null);
  const [approving, setApproving] = useState(false);

  const loadData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const qsParams = new URLSearchParams({
        limit: "100",
      });
      if (stateFilter) qsParams.set("state", stateFilter);
      if (searchQuery.trim()) qsParams.set("q", searchQuery.trim());

      const [p, a, pass, m] = await Promise.all([
        apiRequest<PaymentIntentRecord[]>(`/v1/guardian/payments?${qsParams.toString()}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<AgentRecord[]>("/v1/guardian/agents", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<PassportRecord[]>("/v1/guardian/passports", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<MerchantRecord[]>("/v1/guardian/merchants", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
      ]);
      setPayments(p);
      setAgents(a);
      setPassports(pass);
      setMerchants(m);
      if (!agentId && a[0]) setAgentId(a[0].id);
      if (!passportId && pass[0]) setPassportId(pass[0].id);
      if (!merchantId && m[0]) setMerchantId(m[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load payments data");
    } finally {
      setLoading(false);
    }
  }, [agentId, merchantId, passportId, searchQuery, session, stateFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredPayments = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return payments.filter((p) => {
      const matchesState = stateFilter ? p.state === stateFilter : true;
      if (!matchesState) return false;
      if (!q) return true;
      return (
        p.id.toLowerCase().includes(q) ||
        p.agent_id.toLowerCase().includes(q) ||
        p.merchant_id.toLowerCase().includes(q) ||
        p.quote_hash.toLowerCase().includes(q)
      );
    });
  }, [payments, searchQuery, stateFilter]);

  const pagedPayments = useMemo(() => {
    return filteredPayments.slice(offset, offset + limit);
  }, [filteredPayments, offset, limit]);

  async function handleSubmitProposal(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const amtMinor = Math.round(Number.parseFloat(amountUsd) * 100);
      const res = await apiRequest<{
        payment_intent: PaymentIntentRecord;
        decision: { outcome: string; reason_codes?: string[] };
      }>("/v1/guardian/proposals", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          agent_id: agentId,
          passport_id: passportId,
          merchant_id: merchantId,
          amount_minor: amtMinor,
          currency,
          item_summary: itemSummary,
          line_items: [
            {
              sku: "SKU-AUTO-01",
              title: itemSummary,
              quantity: 1,
              unit_price_minor: amtMinor,
            },
          ],
          rationale,
        },
      });
      const outcome = res.decision.outcome;
      setNotice(
        `Proposal submitted. Intent ${truncateId(res.payment_intent.id)} created with outcome [${outcome}].`,
      );
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Proposal failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleQuickApprove(intent: PaymentIntentRecord) {
    if (!session) return;
    setApproving(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(`/v1/guardian/payments/${intent.id}/approve`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          approver_id: session.email,
          approved: true,
          comment: "Approved in AEGIS console",
        },
      });
      setConfirmApprove(null);
      setNotice(`Approved payment ${truncateId(intent.id)}. Budget reserved.`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  }

  const awaitingApproval = payments.filter((p) => p.state === "AWAITING_APPROVAL");

  return (
    <AppShell
      title="Payments & Authorization Gates"
      subtitle="Deterministic agent payment proposals, state-machine transitions, and PayPal Sandbox capture execution."
    >
      {error && (
        <div role="alert" className="mb-4 border border-[#4A2828] bg-[#211212] p-3 font-mono text-xs text-[#EF5350]">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mb-4 border border-[#3A4A28] bg-[#162112] p-3 font-mono text-xs text-aegis-accent">
          {notice}
        </div>
      )}

      {/* Pending Human Approvals Queue */}
      {awaitingApproval.length > 0 && (
        <section className="mb-6 border border-[#4A3728] bg-[#211812] p-5 rounded-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#4A3728] pb-3">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper font-semibold">
                OPERATOR ESCALATION GATE
              </span>
              <h2 className="mt-0.5 text-sm font-semibold text-aegis-text-primary">
                Pending Human Approvals ({awaitingApproval.length})
              </h2>
            </div>
            <span className="font-mono text-[10px] text-aegis-copper">MANDATORY SIGN-OFF REQUIRED</span>
          </div>

          <div className="mt-3 space-y-2">
            {awaitingApproval.map((intent) => (
              <div
                key={intent.id}
                className="flex flex-wrap items-center justify-between gap-3 border border-[#4A3728] bg-aegis-card p-3 font-mono text-xs"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <Link href={`/payments/${intent.id}`} className="text-aegis-accent hover:underline font-semibold">
                    {truncateId(intent.id, 14)}
                  </Link>
                  <span className="text-aegis-text-primary font-bold tabular-nums">
                    {formatMinorCurrency(intent.amount_minor, intent.currency)}
                  </span>
                  <span className="text-aegis-text-faint">{formatIsoDateTime(intent.created_at)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Link
                    href={`/payments/${intent.id}`}
                    className="border border-aegis-border bg-aegis-surface px-2.5 py-1 text-aegis-text-muted hover:text-aegis-text-primary"
                  >
                    INSPECT
                  </Link>
                  {hasPermission("approvals:decide") && (
                    <button
                      type="button"
                      onClick={() => setConfirmApprove(intent)}
                      className="border border-aegis-accent bg-aegis-accent px-3 py-1 font-bold text-aegis-bg hover:bg-aegis-accent-hover"
                    >
                      APPROVE
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Submit Proposal Form */}
      {hasPermission("proposals:write") && (
        <section className="mb-8 border border-aegis-border bg-aegis-surface p-5 rounded-sm">
          <div className="flex items-center justify-between border-b border-aegis-border pb-3">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                INTENT DISPATCH
              </span>
              <h2 className="mt-0.5 text-sm font-semibold text-aegis-text-primary">Submit Purchase Proposal</h2>
            </div>
            <span className="font-mono text-[10px] text-aegis-text-faint">IMMUTABLE QUOTE HASH</span>
          </div>

          <form onSubmit={handleSubmitProposal} className="mt-4 grid gap-4 md:grid-cols-3 font-mono text-xs">
            <div>
              <label htmlFor="proposal-agent" className="block uppercase text-aegis-text-muted">
                Agent <span className="text-aegis-accent">*</span>
              </label>
              <select
                id="proposal-agent"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id} className="bg-aegis-surface">
                    {a.name} [{a.status}]
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="proposal-passport" className="block uppercase text-aegis-text-muted">
                Spending Passport <span className="text-aegis-accent">*</span>
              </label>
              <select
                id="proposal-passport"
                value={passportId}
                onChange={(e) => setPassportId(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              >
                {passports.map((p) => (
                  <option key={p.id} value={p.id} className="bg-aegis-surface">
                    {truncateId(p.id)} · {formatMinorCurrency(p.total_budget_minor - p.spent_minor - p.reserved_minor, p.currency)} avail
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="proposal-merchant" className="block uppercase text-aegis-text-muted">
                Merchant / Vendor <span className="text-aegis-accent">*</span>
              </label>
              <select
                id="proposal-merchant"
                value={merchantId}
                onChange={(e) => setMerchantId(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              >
                {merchants.map((m) => (
                  <option key={m.id} value={m.id} className="bg-aegis-surface">
                    {m.name} [{m.category}]
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="proposal-amount" className="block uppercase text-aegis-text-muted">
                Amount ({currency}) <span className="text-aegis-accent">*</span>
              </label>
              <input
                id="proposal-amount"
                type="number"
                step="0.01"
                min="0.01"
                required
                value={amountUsd}
                onChange={(e) => setAmountUsd(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary tabular-nums focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="proposal-currency" className="block uppercase text-aegis-text-muted">
                Currency Code
              </label>
              <input
                id="proposal-currency"
                type="text"
                maxLength={3}
                required
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="proposal-summary" className="block uppercase text-aegis-text-muted">
                Item Summary
              </label>
              <input
                id="proposal-summary"
                type="text"
                required
                value={itemSummary}
                onChange={(e) => setItemSummary(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <div className="md:col-span-2">
              <label htmlFor="proposal-rationale" className="block uppercase text-aegis-text-muted">
                Business & Audit Rationale
              </label>
              <input
                id="proposal-rationale"
                type="text"
                required
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <div className="flex items-end">
              <button
                type="submit"
                disabled={submitting || agents.length === 0 || passports.length === 0 || merchants.length === 0}
                className="w-full border border-aegis-accent bg-aegis-accent py-2 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50 transition-colors shadow-editorial"
              >
                {submitting ? "Evaluating Policy…" : "Evaluate & Dispatch"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Payment Intents Section */}
      <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-text-faint">
              PAYMENT STATE MACHINE
            </span>
            <h2 className="text-sm font-semibold text-aegis-text-primary">
              Payment Intents ({filteredPayments.length})
            </h2>
          </div>

          <div className="flex flex-wrap items-center gap-3 font-mono">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setOffset(0);
              }}
              placeholder="Search by ID, hash, agent..."
              className="w-64 border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
            />
            <div className="flex items-center gap-1.5 text-xs text-aegis-text-muted">
              <span>LIMIT:</span>
              <select
                id="payment-limit-select"
                value={limit}
                onChange={(e) => {
                  setLimit(Number(e.target.value));
                  setOffset(0);
                }}
                className="border border-aegis-border bg-aegis-card px-2 py-1 text-xs text-aegis-text-primary focus:outline-none"
              >
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
          </div>
        </div>

        {/* Canonical 11 PaymentState Filter Chips */}
        <div className="my-4 flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
          <span className="mr-1 text-aegis-text-faint uppercase text-[10px]">FILTER STATE:</span>
          <button
            type="button"
            onClick={() => {
              setStateFilter("");
              setOffset(0);
            }}
            className={`border px-2.5 py-0.5 uppercase transition-colors ${
              stateFilter === ""
                ? "border-aegis-accent bg-aegis-secondary text-aegis-accent font-bold"
                : "border-aegis-border bg-aegis-card text-aegis-text-muted hover:text-aegis-text-primary"
            }`}
          >
            ALL
          </button>
          {CANONICAL_PAYMENT_STATES.map((st) => {
            const isSelected = stateFilter === st;
            return (
              <button
                key={st}
                type="button"
                onClick={() => {
                  setStateFilter(isSelected ? "" : st);
                  setOffset(0);
                }}
                className={`border px-2 py-0.5 uppercase transition-colors ${
                  isSelected
                    ? "border-aegis-accent bg-aegis-secondary text-aegis-accent font-bold"
                    : "border-aegis-border bg-aegis-card text-aegis-text-muted hover:text-aegis-text-primary"
                }`}
              >
                {st}
              </button>
            );
          })}
        </div>

        {/* Accessible Table Structure */}
        <div tabIndex={0} role="region" aria-labelledby="payments-table-caption" className="table-wrapper">
          <table className="aegis-table">
            <caption id="payments-table-caption" className="sr-only">Organization payment intents</caption>
            <thead>
              <tr>
                <th scope="col">INTENT IDENTIFIER</th>
                <th scope="col">STATE</th>
                <th scope="col">AMOUNT</th>
                <th scope="col">QUOTE INTEGRITY HASH</th>
                <th scope="col">UPDATED AT</th>
                <th scope="col" className="text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                    RETRIEVING INTENT RECORDS…
                  </td>
                </tr>
              ) : pagedPayments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                    {searchQuery || stateFilter
                      ? "NO PAYMENT INTENTS MATCHING APPLIED FILTERS."
                      : "NO INTENT RECORDS RECORDED IN THIS TENANT."}
                  </td>
                </tr>
              ) : (
                pagedPayments.map((p) => (
                  <tr key={p.id}>
                    <td className="font-mono text-xs font-semibold text-aegis-accent">
                      <Link href={`/payments/${p.id}`} className="hover:underline">
                        {truncateId(p.id, 14)}
                      </Link>
                    </td>
                    <td>
                      <StatusBadge label={p.state} />
                    </td>
                    <td className="font-mono text-xs font-bold tabular-nums text-aegis-text-primary">
                      {formatMinorCurrency(p.amount_minor, p.currency)}
                    </td>
                    <td className="font-mono text-xs text-aegis-text-faint">{truncateId(p.quote_hash, 12)}</td>
                    <td className="font-mono text-xs text-aegis-text-muted tabular-nums">
                      {formatIsoDateTime(p.updated_at)}
                    </td>
                    <td className="text-right font-mono text-xs">
                      <div className="inline-flex items-center gap-2">
                        <Link
                          href={`/payments/${p.id}`}
                          className="border border-aegis-border bg-aegis-card px-2.5 py-0.5 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary transition-colors"
                        >
                          DETAIL
                        </Link>
                        <Link
                          href={`/ghostpay/replay/${p.id}`}
                          className="border border-[#4A3728] bg-[#211812] px-2.5 py-0.5 text-aegis-copper hover:bg-[#D58A62]/20 transition-colors"
                        >
                          REPLAY
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Payments Pagination Bar */}
        {filteredPayments.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 font-mono text-xs text-aegis-text-faint">
            <div>
              SHOWING {Math.min(filteredPayments.length, offset + 1)}–{Math.min(filteredPayments.length, offset + limit)} OF {filteredPayments.length} INTENTS
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
                className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
              >
                PREV
              </button>
              <span>
                PAGE {Math.floor(offset / limit) + 1} OF {Math.max(1, Math.ceil(filteredPayments.length / limit))}
              </span>
              <button
                type="button"
                disabled={offset + limit >= filteredPayments.length}
                onClick={() => setOffset((prev) => prev + limit)}
                className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
              >
                NEXT
              </button>
            </div>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={Boolean(confirmApprove)}
        title="Approve Agent Payment Proposal"
        description={
          confirmApprove
            ? `Approve ${formatMinorCurrency(confirmApprove.amount_minor, confirmApprove.currency)} for intent ${truncateId(confirmApprove.id, 12)} and reserve budget under passport locks?`
            : ""
        }
        confirmLabel="Approve & Reserve Budget"
        busy={approving}
        onCancel={() => setConfirmApprove(null)}
        onConfirm={() => {
          if (confirmApprove) {
            void handleQuickApprove(confirmApprove);
          }
        }}
      />
    </AppShell>
  );
}
