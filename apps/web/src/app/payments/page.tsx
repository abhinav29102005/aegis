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

      const [p, a, ps, m] = await Promise.all([
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
      setPassports(ps);
      setMerchants(m);
      setAgentId((prev) => prev || a[0]?.id || "");
      setPassportId((prev) => prev || ps.find((item) => item.status === "ACTIVE")?.id || ps[0]?.id || "");
      setMerchantId((prev) => prev || m[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load payments");
    } finally {
      setLoading(false);
    }
  }, [searchQuery, session, stateFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Client-side filtering & search
  const filteredPayments = useMemo(() => {
    let result = payments;
    if (stateFilter) {
      result = result.filter((p) => p.state === stateFilter);
    }
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      result = result.filter(
        (p) =>
          p.id.toLowerCase().includes(q) ||
          p.correlation_id.toLowerCase().includes(q) ||
          p.quote_hash.toLowerCase().includes(q) ||
          p.agent_id.toLowerCase().includes(q) ||
          p.merchant_id.toLowerCase().includes(q) ||
          p.state.toLowerCase().includes(q),
      );
    }
    return result;
  }, [payments, searchQuery, stateFilter]);

  const pagedPayments = useMemo(() => {
    return filteredPayments.slice(offset, offset + limit);
  }, [filteredPayments, offset, limit]);

  async function handleSubmitProposal(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError(null);
    setNotice(null);
    const parsedMajor = Number(amountUsd);
    if (!Number.isFinite(parsedMajor) || parsedMajor <= 0) {
      setError("Enter a valid positive payment amount.");
      return;
    }
    const merchant = merchants.find((m) => m.id === merchantId);
    if (!merchant || !agentId || !passportId) {
      setError("Select an agent, active passport, and registered merchant before submitting.");
      return;
    }
    const amountMinor = Math.round(parsedMajor * 100);
    setSubmitting(true);
    try {
      const res = await apiRequest<{
        payment_intent: PaymentIntentRecord;
        decision: { outcome: string; reason_codes: string[] };
      }>("/v1/guardian/proposals", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          agent_id: agentId,
          passport_id: passportId,
          merchant_id: merchant.id,
          merchant_name: merchant.name,
          merchant_category: merchant.category,
          amount_minor: amountMinor,
          currency: currency.toUpperCase(),
          item_summary: itemSummary.trim(),
          line_items: [
            {
              sku: "ITEM-1",
              description: itemSummary.trim(),
              quantity: 1,
              unit_price_minor: amountMinor,
            },
          ],
          rationale: rationale.trim(),
          idempotency_key: `ui-${crypto.randomUUID()}`,
        },
      });
      setNotice(
        `Proposal created (${truncateId(res.payment_intent.id)}) with deterministic outcome ${res.decision.outcome}.`,
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
    try {
      await apiRequest(`/v1/guardian/proposals/${intent.id}/approve`, {
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
      title="Payments & Approvals"
      subtitle="Submit deterministic agent proposals, inspect policy verdicts, and control checkout capture."
    >
      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mb-4 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
          {notice}
        </div>
      )}

      {awaitingApproval.length > 0 && (
        <section className="mb-6 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-amber-200">
                Pending Human Approvals ({awaitingApproval.length})
              </h2>
              <p className="text-xs text-amber-100/80">
                High-value or escalated proposals require explicit human approval before reservation and checkout.
              </p>
            </div>
          </div>
          <div className="mt-3 space-y-2">
            {awaitingApproval.map((intent) => (
              <div
                key={intent.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/30 bg-aegis-surface px-3 py-2 text-sm"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <Link href={`/payments/${intent.id}`} className="font-mono text-xs text-sky-300 hover:underline">
                    {truncateId(intent.id, 12)}
                  </Link>
                  <span className="font-semibold text-white">
                    {formatMinorCurrency(intent.amount_minor, intent.currency)}
                  </span>
                  <span className="text-xs text-slate-400">{formatIsoDateTime(intent.created_at)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Link
                    href={`/payments/${intent.id}`}
                    className="rounded-md border border-aegis-border px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
                  >
                    Inspect
                  </Link>
                  {hasPermission("approvals:decide") && (
                    <button
                      type="button"
                      onClick={() => setConfirmApprove(intent)}
                      className="rounded-md bg-amber-400 px-2.5 py-1 text-xs font-semibold text-slate-950 hover:bg-amber-300"
                    >
                      Approve
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {hasPermission("proposals:write") && (
        <section className="mb-6 rounded-xl border border-aegis-border bg-aegis-surface p-5">
          <h2 className="text-sm font-semibold text-white">Submit New Purchase Proposal</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Creates an immutable quote snapshot, evaluates deterministic policy, and records a signed financial event.
          </p>
          <form onSubmit={handleSubmitProposal} className="mt-4 grid gap-4 md:grid-cols-3">
            <div>
              <label htmlFor="proposal-agent" className="block text-xs font-medium text-slate-300">
                Agent
              </label>
              <select
                id="proposal-agent"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.status})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="proposal-passport" className="block text-xs font-medium text-slate-300">
                Spending Passport
              </label>
              <select
                id="proposal-passport"
                value={passportId}
                onChange={(e) => setPassportId(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              >
                {passports.map((p) => (
                  <option key={p.id} value={p.id}>
                    {truncateId(p.id)} · {formatMinorCurrency(p.total_budget_minor - p.spent_minor - p.reserved_minor, p.currency)} avail ({p.status})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="proposal-merchant" className="block text-xs font-medium text-slate-300">
                Merchant
              </label>
              <select
                id="proposal-merchant"
                value={merchantId}
                onChange={(e) => setMerchantId(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              >
                {merchants.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} ({m.category})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="proposal-amount" className="block text-xs font-medium text-slate-300">
                Amount ({currency})
              </label>
              <input
                id="proposal-amount"
                type="number"
                step="0.01"
                min="0.01"
                required
                value={amountUsd}
                onChange={(e) => setAmountUsd(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label htmlFor="proposal-currency" className="block text-xs font-medium text-slate-300">
                Currency
              </label>
              <input
                id="proposal-currency"
                type="text"
                maxLength={3}
                required
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label htmlFor="proposal-summary" className="block text-xs font-medium text-slate-300">
                Item Summary
              </label>
              <input
                id="proposal-summary"
                type="text"
                required
                value={itemSummary}
                onChange={(e) => setItemSummary(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              />
            </div>
            <div className="md:col-span-2">
              <label htmlFor="proposal-rationale" className="block text-xs font-medium text-slate-300">
                Business Rationale
              </label>
              <input
                id="proposal-rationale"
                type="text"
                required
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white"
              />
            </div>
            <div className="flex items-end">
              <button
                type="submit"
                disabled={submitting || agents.length === 0 || passports.length === 0 || merchants.length === 0}
                className="w-full rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
              >
                {submitting ? "Evaluating Policy…" : "Submit Proposal"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Payment Intents Section */}
      <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <h2 className="text-base font-semibold text-white">
            Payment Intents ({filteredPayments.length})
          </h2>

          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setOffset(0);
                }}
                placeholder="Search intents (ID, hash, agent)..."
                className="w-64 rounded-lg border border-aegis-border bg-aegis-bg px-3 py-1.5 text-xs text-white placeholder-slate-400"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery("");
                    setOffset(0);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-300">
              <label htmlFor="payment-limit-select">Limit:</label>
              <select
                id="payment-limit-select"
                value={limit}
                onChange={(e) => {
                  setLimit(Number(e.target.value));
                  setOffset(0);
                }}
                className="rounded border border-aegis-border bg-aegis-bg px-2 py-1 text-xs text-white"
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
        <div className="my-4 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs font-medium text-slate-400">State:</span>
          <button
            type="button"
            onClick={() => {
              setStateFilter("");
              setOffset(0);
            }}
            className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
              stateFilter === ""
                ? "bg-sky-500 text-slate-950 font-semibold shadow-sm"
                : "border border-aegis-border bg-aegis-bg text-slate-300 hover:bg-slate-800"
            }`}
          >
            All
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
                className={`rounded-full px-2.5 py-1 text-xs font-mono transition ${
                  isSelected
                    ? "bg-sky-500 text-slate-950 font-semibold shadow-sm"
                    : "border border-aegis-border bg-aegis-bg text-slate-300 hover:bg-slate-800"
                }`}
              >
                {st}
              </button>
            );
          })}
        </div>

        {/* Accessible Table Structure with .table-wrapper and <th scope="col"> */}
        <div tabIndex={0} role="region" aria-labelledby="payments-table-caption" className="table-wrapper">
          <table className="aegis-table w-full text-left text-sm">
            <caption id="payments-table-caption" className="sr-only">Organization payment intents</caption>
            <thead>
              <tr>
                <th scope="col">Intent</th>
                <th scope="col">State</th>
                <th scope="col">Amount</th>
                <th scope="col">Quote Hash</th>
                <th scope="col">Updated</th>
                <th scope="col" className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400 py-6">
                    Loading payment intents…
                  </td>
                </tr>
              ) : pagedPayments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400 py-6">
                    {searchQuery || stateFilter
                      ? "No payment intents matching current filters."
                      : "No payment intents found. Register an agent, passport, and merchant, then submit a proposal above."}
                  </td>
                </tr>
              ) : (
                pagedPayments.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/30">
                    <td className="font-mono text-xs text-sky-300">
                      <Link href={`/payments/${p.id}`} className="hover:underline">
                        {truncateId(p.id, 12)}
                      </Link>
                    </td>
                    <td>
                      <StatusBadge label={p.state} />
                    </td>
                    <td className="font-medium text-white">
                      {formatMinorCurrency(p.amount_minor, p.currency)}
                    </td>
                    <td className="font-mono text-xs text-slate-400">{truncateId(p.quote_hash, 12)}</td>
                    <td className="text-xs text-slate-400">{formatIsoDateTime(p.updated_at)}</td>
                    <td className="text-right">
                      <div className="inline-flex items-center gap-2">
                        <Link
                          href={`/payments/${p.id}`}
                          className="rounded-md border border-aegis-border px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
                        >
                          Detail
                        </Link>
                        <Link
                          href={`/ghostpay/replay/${p.id}`}
                          className="rounded-md border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 text-xs text-sky-300 hover:bg-sky-500/20"
                        >
                          Replay
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
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 text-xs text-slate-400">
            <div>
              Showing {Math.min(filteredPayments.length, offset + 1)} to {Math.min(filteredPayments.length, offset + limit)} of {filteredPayments.length} intents
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Previous
              </button>
              <span>
                Page {Math.floor(offset / limit) + 1} of {Math.max(1, Math.ceil(filteredPayments.length / limit))}
              </span>
              <button
                type="button"
                disabled={offset + limit >= filteredPayments.length}
                onClick={() => setOffset((prev) => prev + limit)}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Next
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
            ? `Approve ${formatMinorCurrency(confirmApprove.amount_minor, confirmApprove.currency)} for intent ${truncateId(confirmApprove.id, 12)} and lock funds under budget reservation?`
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
