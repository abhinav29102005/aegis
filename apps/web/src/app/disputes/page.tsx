"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  apiRequest,
  type DisputeCaseRecord,
  type PaymentIntentRecord,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

function renderSlaBadge(dueIso?: string | null) {
  if (!dueIso) {
    return <span className="text-xs text-slate-500">No SLA</span>;
  }
  const due = new Date(dueIso).getTime();
  const now = Date.now();
  const diffMs = due - now;
  if (diffMs <= 0) {
    const overdueHrs = Math.floor(Math.abs(diffMs) / (1000 * 60 * 60));
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-xs font-semibold text-rose-300">
        <span className="h-1.5 w-1.5 rounded-full bg-rose-400 animate-pulse" />
        OVERDUE ({overdueHrs}h)
      </span>
    );
  }
  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  const isUrgent = hours < 48;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${
        isUrgent
          ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
          : "border-sky-500/40 bg-sky-500/10 text-sky-300"
      }`}
      title={`Due: ${formatIsoDateTime(dueIso)}`}
    >
      <span>⏱</span> {days > 0 ? `${days}d ${remainingHours}h` : `${hours}h`} left
    </span>
  );
}

export default function DisputesPage() {
  const { session, hasPermission } = useAuth();
  const [cases, setCases] = useState<DisputeCaseRecord[]>([]);
  const [payments, setPayments] = useState<PaymentIntentRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [syntheticFilter, setSyntheticFilter] = useState<"ALL" | "REAL" | "SYNTHETIC">("ALL");
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // New Case Modal / Form State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creatingCase, setCreatingCase] = useState(false);
  const [newPaymentIntentId, setNewPaymentIntentId] = useState("");
  const [newCorrelationId, setNewCorrelationId] = useState("");
  const [newReason, setNewReason] = useState("MERCHANDISE_OR_SERVICES_NOT_RECEIVED");
  const [newBuyerClaim, setNewBuyerClaim] = useState("");
  const [newAmountUsd, setNewAmountUsd] = useState("50.00");
  const [newCurrency, setNewCurrency] = useState("USD");
  const [newSourceType, setNewSourceType] = useState<"PAYPAL_SANDBOX" | "SYNTHETIC_DEMO" | "MANUAL">("PAYPAL_SANDBOX");
  const [newPaypalDisputeId, setNewPaypalDisputeId] = useState("");

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

      const [rows, payResp] = await Promise.all([
        apiRequest<DisputeCaseRecord[]>(`/v1/disputeos/cases${query}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<PaymentIntentRecord[]>("/v1/guardian/payments?limit=50", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }).catch(() => [] as PaymentIntentRecord[]),
      ]);

      setCases(rows);
      setPayments(payResp);
      if (payResp.length > 0 && !newPaymentIntentId) {
        setNewPaymentIntentId(payResp[0].id);
        setNewCorrelationId(payResp[0].correlation_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dispute cases");
    } finally {
      setLoading(false);
    }
  }, [newPaymentIntentId, session, statusFilter, syntheticFilter]);

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

  function handleOpenCreateModal() {
    setNewCorrelationId(crypto.randomUUID());
    if (payments.length > 0) {
      setNewPaymentIntentId(payments[0].id);
    }
    setNewBuyerClaim("Buyer claims package did not arrive by the promised delivery date.");
    setShowCreateModal(true);
  }

  async function handleCreateCase(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    if (!newPaymentIntentId.trim() || !newReason.trim() || !newBuyerClaim.trim()) {
      setError("Payment Intent ID, Reason, and Buyer Claim are required.");
      return;
    }
    const amountMinor = Math.round(Number(newAmountUsd) * 100);
    if (!Number.isFinite(amountMinor) || amountMinor <= 0) {
      setError("Please specify a valid positive amount.");
      return;
    }

    setCreatingCase(true);
    setError(null);
    setNotice(null);
    try {
      const created = await apiRequest<DisputeCaseRecord>("/v1/disputeos/cases", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          correlation_id: newCorrelationId.trim() || crypto.randomUUID(),
          payment_intent_id: newPaymentIntentId.trim(),
          reason: newReason.trim(),
          buyer_claim: newBuyerClaim.trim(),
          amount_minor: amountMinor,
          currency: newCurrency.toUpperCase(),
          source_type: newSourceType,
          is_synthetic: newSourceType === "SYNTHETIC_DEMO",
          paypal_dispute_id: newPaypalDisputeId.trim() || null,
        },
      });
      setNotice(`Dispute case ${truncateId(created.id, 12)} created successfully (${newSourceType}).`);
      setShowCreateModal(false);
      await loadCases();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create dispute case");
    } finally {
      setCreatingCase(false);
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

      {/* Action and Filter Header */}
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
            <option value="RESOLVED">RESOLVED</option>
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

        <div className="flex flex-wrap items-center gap-2">
          {hasPermission("disputes:write") && (
            <>
              <button
                type="button"
                onClick={handleOpenCreateModal}
                className="rounded-lg bg-sky-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400"
              >
                + New Dispute Case
              </button>
              <button
                type="button"
                disabled={seeding}
                onClick={() => void handleSeedSyntheticDemo()}
                className="rounded-lg border border-sky-500/40 bg-sky-500/15 px-3.5 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-500/25 disabled:opacity-50"
              >
                {seeding ? "Seeding Demo Case…" : "Seed Synthetic Demo Case"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Case Table */}
      <section className="rounded-xl border border-aegis-border bg-aegis-surface">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Organization dispute cases</caption>
            <thead className="border-b border-aegis-border bg-aegis-panel/60 text-xs uppercase text-slate-400">
              <tr>
                <th scope="col" className="px-4 py-3">Case ID</th>
                <th scope="col" className="px-4 py-3">Reason</th>
                <th scope="col" className="px-4 py-3">Amount</th>
                <th scope="col" className="px-4 py-3">Status</th>
                <th scope="col" className="px-4 py-3">Origin</th>
                <th scope="col" className="px-4 py-3">Response SLA</th>
                <th scope="col" className="px-4 py-3">Evidence</th>
                <th scope="col" className="px-4 py-3">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-aegis-border">
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-slate-400">
                    Loading dispute cases…
                  </td>
                </tr>
              ) : cases.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-slate-400">
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
                      {c.is_synthetic ? (
                        <StatusBadge label="SYNTHETIC_DEMO" />
                      ) : (
                        <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                          {c.source_type}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {renderSlaBadge(c.response_due_by)}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-300">{c.evidence_ids?.length || 0} items</td>
                    <td className="px-4 py-3 text-xs text-slate-400">{formatIsoDateTime(c.updated_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Non-synthetic POST /v1/disputeos/cases Modal */}
      {showCreateModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-dispute-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4"
        >
          <div className="w-full max-w-lg rounded-2xl border border-aegis-border bg-aegis-surface p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-aegis-border pb-3">
              <h2 id="create-dispute-modal-title" className="text-base font-semibold text-white">
                Open New Dispute Case
              </h2>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateCase} className="mt-4 space-y-4 text-xs">
              <div>
                <label htmlFor="case-source-type" className="block font-medium text-slate-300">
                  Source Type
                </label>
                <select
                  id="case-source-type"
                  value={newSourceType}
                  onChange={(e) =>
                    setNewSourceType(e.target.value as "PAYPAL_SANDBOX" | "SYNTHETIC_DEMO" | "MANUAL")
                  }
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-white"
                >
                  <option value="PAYPAL_SANDBOX">PAYPAL_SANDBOX (PayPal Dispute Ingestion)</option>
                  <option value="MANUAL">MANUAL (Direct Merchant / Support Dispute)</option>
                  <option value="SYNTHETIC_DEMO">SYNTHETIC_DEMO (Sandbox Demo Only)</option>
                </select>
              </div>

              <div>
                <label htmlFor="case-payment-intent" className="block font-medium text-slate-300">
                  Payment Intent ID
                </label>
                <div className="mt-1 flex gap-2">
                  <input
                    id="case-payment-intent"
                    type="text"
                    value={newPaymentIntentId}
                    onChange={(e) => setNewPaymentIntentId(e.target.value)}
                    placeholder="Enter PaymentIntent UUID..."
                    className="flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 font-mono text-white"
                  />
                  {payments.length > 0 && (
                    <select
                      aria-label="Pick from existing payments"
                      onChange={(e) => {
                        const p = payments.find((x) => x.id === e.target.value);
                        if (p) {
                          setNewPaymentIntentId(p.id);
                          setNewCorrelationId(p.correlation_id);
                          setNewAmountUsd((p.amount_minor / 100).toFixed(2));
                          setNewCurrency(p.currency);
                        }
                      }}
                      value=""
                      className="rounded-lg border border-aegis-border bg-aegis-panel px-2 text-slate-300"
                    >
                      <option value="">Pick intent...</option>
                      {payments.map((p) => (
                        <option key={p.id} value={p.id}>
                          {truncateId(p.id, 10)} (${(p.amount_minor / 100).toFixed(2)})
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="case-amount" className="block font-medium text-slate-300">
                    Disputed Amount
                  </label>
                  <input
                    id="case-amount"
                    type="number"
                    step="0.01"
                    value={newAmountUsd}
                    onChange={(e) => setNewAmountUsd(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-white"
                  />
                </div>
                <div>
                  <label htmlFor="case-currency" className="block font-medium text-slate-300">
                    Currency
                  </label>
                  <input
                    id="case-currency"
                    type="text"
                    value={newCurrency}
                    onChange={(e) => setNewCurrency(e.target.value.toUpperCase())}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 font-mono text-white"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="case-reason" className="block font-medium text-slate-300">
                  Dispute Reason
                </label>
                <select
                  id="case-reason"
                  value={newReason}
                  onChange={(e) => setNewReason(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-white"
                >
                  <option value="MERCHANDISE_OR_SERVICES_NOT_RECEIVED">MERCHANDISE_OR_SERVICES_NOT_RECEIVED</option>
                  <option value="MERCHANDISE_OR_SERVICES_NOT_AS_DESCRIBED">MERCHANDISE_OR_SERVICES_NOT_AS_DESCRIBED</option>
                  <option value="UNAUTHORIZED_TRANSACTION">UNAUTHORIZED_TRANSACTION</option>
                  <option value="CREDIT_NOT_PROCESSED">CREDIT_NOT_PROCESSED</option>
                  <option value="DUPLICATE_TRANSACTION">DUPLICATE_TRANSACTION</option>
                  <option value="INCORRECT_AMOUNT">INCORRECT_AMOUNT</option>
                </select>
              </div>

              <div>
                <label htmlFor="case-claim" className="block font-medium text-slate-300">
                  Buyer Claim Description
                </label>
                <textarea
                  id="case-claim"
                  rows={3}
                  value={newBuyerClaim}
                  onChange={(e) => setNewBuyerClaim(e.target.value)}
                  placeholder="Detail the buyer's claims and assertions..."
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel p-2.5 text-white"
                />
              </div>

              {newSourceType === "PAYPAL_SANDBOX" && (
                <div>
                  <label htmlFor="case-paypal-dispute-id" className="block font-medium text-slate-300">
                    PayPal Dispute ID (optional)
                  </label>
                  <input
                    id="case-paypal-dispute-id"
                    type="text"
                    placeholder="PP-D-12345"
                    value={newPaypalDisputeId}
                    onChange={(e) => setNewPaypalDisputeId(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 font-mono text-white"
                  />
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="rounded-lg border border-aegis-border px-4 py-2 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingCase}
                  className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                >
                  {creatingCase ? "Creating Case…" : "Create Dispute Case"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppShell>
  );
}
