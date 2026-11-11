"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import {
  apiRequest,
  type AgentRecord,
  type MerchantRecord,
  type PassportRecord,
  type PaymentIntentRecord,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

const PAYMENT_STATES = [
  "",
  "PROPOSED",
  "POLICY_EVALUATED",
  "AWAITING_APPROVAL",
  "CHECKOUT_READY",
  "AWAITING_PAYPAL_BUYER",
  "BUYER_APPROVED",
  "CAPTURE_IN_PROGRESS",
  "PENDING_PROVIDER",
  "SUCCEEDED",
  "FAILED",
  "REJECTED",
];

export default function PaymentsPage() {
  const { session, hasPermission } = useAuth();
  const [payments, setPayments] = useState<PaymentIntentRecord[]>([]);
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [passports, setPassports] = useState<PassportRecord[]>([]);
  const [merchants, setMerchants] = useState<MerchantRecord[]>([]);
  const [stateFilter, setStateFilter] = useState("");
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
      const qs = stateFilter ? `?state=${encodeURIComponent(stateFilter)}&limit=100` : "?limit=100";
      const [p, a, ps, m] = await Promise.all([
        apiRequest<PaymentIntentRecord[]>(`/v1/guardian/payments${qs}`, {
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
  }, [session, stateFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

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

      <section className="rounded-xl border border-aegis-border bg-aegis-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border px-5 py-3">
          <h2 className="text-sm font-semibold text-white">Payment Intents</h2>
          <div className="flex items-center gap-2">
            <label htmlFor="state-filter" className="text-xs text-slate-400">
              State:
            </label>
            <select
              id="state-filter"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1 text-xs text-white"
            >
              {PAYMENT_STATES.map((st) => (
                <option key={st || "ALL"} value={st}>
                  {st || "All States"}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Organization payment intents</caption>
            <thead className="border-b border-aegis-border bg-aegis-panel/60 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">Intent</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Quote Hash</th>
                <th className="px-4 py-3">Updated</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-aegis-border">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                    Loading payment intents…
                  </td>
                </tr>
              ) : payments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                    No payment intents found. Register an agent, passport, and merchant, then submit a proposal above.
                  </td>
                </tr>
              ) : (
                payments.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/30">
                    <td className="px-4 py-3 font-mono text-xs text-sky-300">
                      <Link href={`/payments/${p.id}`} className="hover:underline">
                        {truncateId(p.id, 12)}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge label={p.state} />
                    </td>
                    <td className="px-4 py-3 font-medium text-white">
                      {formatMinorCurrency(p.amount_minor, p.currency)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-400">{truncateId(p.quote_hash, 12)}</td>
                    <td className="px-4 py-3 text-xs text-slate-400">{formatIsoDateTime(p.updated_at)}</td>
                    <td className="px-4 py-3 text-right">
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
