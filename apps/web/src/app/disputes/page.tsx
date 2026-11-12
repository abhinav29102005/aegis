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
import { Clock } from "lucide-react";

function renderSlaBadge(dueIso?: string | null) {
  if (!dueIso) {
    return <span className="font-mono text-[11px] text-aegis-text-faint">NO SLA</span>;
  }
  const due = new Date(dueIso).getTime();
  const now = Date.now();
  const diffMs = due - now;
  if (diffMs <= 0) {
    const overdueHrs = Math.floor(Math.abs(diffMs) / (1000 * 60 * 60));
    return (
      <span className="inline-flex items-center gap-1.5 border border-[#4A2828] bg-[#211212] px-2 py-0.5 font-mono text-[10px] font-bold text-[#EF5350] uppercase tracking-wider">
        <span className="h-1.5 w-1.5 rounded-full bg-[#EF5350] animate-pulse" />
        OVERDUE (+{overdueHrs}h)
      </span>
    );
  }
  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  const isUrgent = hours < 48;
  return (
    <span
      className={`inline-flex items-center gap-1 border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${
        isUrgent
          ? "border-[#4A3728] bg-[#211812] text-aegis-copper font-semibold"
          : "border-aegis-border bg-aegis-card text-aegis-text-muted"
      }`}
      title={`Due: ${formatIsoDateTime(dueIso)}`}
    >
      <Clock className="h-2.5 w-2.5" />
      <span>{days > 0 ? `${days}d ${remainingHours}h` : `${hours}h`} REMAINING</span>
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
  const [newReason, setNewReason] = useState("MERCHANDISE_OR_SERVICE_NOT_RECEIVED");
  const [newBuyerClaim, setNewBuyerClaim] = useState("");
  const [newAmountUsd, setNewAmountUsd] = useState("45.00");
  const [newCurrency, setNewCurrency] = useState("USD");
  const [newSourceType, setNewSourceType] = useState<"PAYPAL_SANDBOX" | "SYNTHETIC_DEMO" | "MANUAL">("PAYPAL_SANDBOX");
  const [newPaypalDisputeId, setNewPaypalDisputeId] = useState("");

  const loadCases = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (statusFilter) qs.set("status", statusFilter);
      if (syntheticFilter === "SYNTHETIC") qs.set("is_synthetic", "true");
      else if (syntheticFilter === "REAL") qs.set("is_synthetic", "false");

      const [casesRes, payRes] = await Promise.all([
        apiRequest<DisputeCaseRecord[]>(`/v1/disputeos/cases?${qs.toString()}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<PaymentIntentRecord[]>("/v1/guardian/payments?limit=25", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
      ]);

      setCases(casesRes);
      setPayments(payRes);
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
      const res = await apiRequest<{ case_id: string; evidence_records: number }>(
        "/v1/disputeos/demo-seed",
        {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
        },
      );
      setNotice(
        `Synthetic demo case created (${truncateId(res.case_id, 10)}) with ${res.evidence_records} evidence artifacts.`,
      );
      await loadCases();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to seed demo dispute case");
    } finally {
      setSeeding(false);
    }
  }

  function handleOpenCreateModal() {
    setError(null);
    setNotice(null);
    if (payments.length > 0 && !newPaymentIntentId) {
      setNewPaymentIntentId(payments[0].id);
      setNewCorrelationId(payments[0].correlation_id);
      setNewAmountUsd((payments[0].amount_minor / 100).toFixed(2));
      setNewCurrency(payments[0].currency);
    }
    setShowCreateModal(true);
  }

  async function handleCreateCase(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    if (!newPaymentIntentId.trim()) {
      setError("Payment Intent ID is required.");
      return;
    }
    const amountMinor = Math.round(Number.parseFloat(newAmountUsd) * 100);
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
      title="DisputeOS Evidence & Adjudication Workspace"
      subtitle="Evidence provenance graphs, automated contradiction analysis, and human-signed dispute responses."
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

      {/* Action and Filter Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border border-aegis-border bg-aegis-surface p-4 rounded-sm">
        <div className="flex flex-wrap items-center gap-3 font-mono text-xs">
          <div className="flex items-center gap-1.5 text-aegis-text-muted">
            <span className="text-[10px] text-aegis-text-faint uppercase">STATUS:</span>
            <select
              aria-label="Filter by case status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary focus:outline-none"
            >
              <option value="">ALL STATUSES</option>
              <option value="OPEN">OPEN</option>
              <option value="UNDER_INVESTIGATION">UNDER_INVESTIGATION</option>
              <option value="DRAFT_READY">DRAFT_READY</option>
              <option value="APPROVED_FOR_SUBMISSION">APPROVED_FOR_SUBMISSION</option>
              <option value="SUBMITTED">SUBMITTED</option>
              <option value="RESOLVED">RESOLVED</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 text-aegis-text-muted">
            <span className="text-[10px] text-aegis-text-faint uppercase">ORIGIN:</span>
            <select
              aria-label="Filter by data origin"
              value={syntheticFilter}
              onChange={(e) => setSyntheticFilter(e.target.value as "ALL" | "REAL" | "SYNTHETIC")}
              className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-xs text-aegis-text-primary focus:outline-none"
            >
              <option value="ALL">ALL ORIGINS</option>
              <option value="REAL">PRODUCTION / LIVE CASES</option>
              <option value="SYNTHETIC">SYNTHETIC DEMO ONLY</option>
            </select>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 font-mono text-xs">
          {hasPermission("disputes:write") && (
            <>
              <button
                type="button"
                onClick={handleOpenCreateModal}
                className="border border-aegis-accent bg-aegis-accent px-4 py-1.5 font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover transition-colors shadow-editorial"
              >
                + New Dispute Case
              </button>
              <button
                type="button"
                disabled={seeding}
                onClick={() => void handleSeedSyntheticDemo()}
                className="border border-[#4A3728] bg-[#211812] px-3.5 py-1.5 font-semibold text-aegis-copper hover:bg-[#D58A62]/20 disabled:opacity-50 transition-colors uppercase"
              >
                {seeding ? "Seeding…" : "Seed Synthetic Demo Case"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Case Table */}
      <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
        <div className="border-b border-aegis-border pb-3 mb-4 flex items-center justify-between">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-text-faint">
              CASE ADJUDICATION DOSSIERS
            </span>
            <h2 className="text-sm font-semibold text-aegis-text-primary">Active Cases ({cases.length})</h2>
          </div>
          <span className="font-mono text-[10px] text-aegis-text-faint">DUAL-SIGN SUBMISSION REQUIRED</span>
        </div>

        <div tabIndex={0} role="region" aria-label="Organization dispute cases" className="table-wrapper">
          <table className="aegis-table">
            <caption className="sr-only">Organization dispute cases</caption>
            <thead>
              <tr>
                <th scope="col">CASE IDENTIFIER</th>
                <th scope="col">DISPUTE REASON</th>
                <th scope="col">CLAIM AMOUNT</th>
                <th scope="col">CASE STATUS</th>
                <th scope="col">DATA ORIGIN</th>
                <th scope="col">RESPONSE SLA</th>
                <th scope="col">EVIDENCE COUNT</th>
                <th scope="col">CHRONO UPDATED</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                    RETRIEVING DISPUTE CASES…
                  </td>
                </tr>
              ) : cases.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center font-mono text-xs text-aegis-text-muted py-6">
                    NO DISPUTE CASES RECORDED FOR THIS TENANT.
                  </td>
                </tr>
              ) : (
                cases.map((c) => (
                  <tr key={c.id}>
                    <td className="font-mono text-xs font-semibold text-aegis-accent">
                      <Link href={`/disputes/${c.id}`} className="hover:underline">
                        {truncateId(c.id, 14)}
                      </Link>
                    </td>
                    <td className="font-sans text-xs text-aegis-text-primary max-w-xs truncate">{c.reason}</td>
                    <td className="font-mono text-xs font-bold text-aegis-text-primary tabular-nums">
                      {formatMinorCurrency(c.amount_minor, c.currency)}
                    </td>
                    <td>
                      <StatusBadge label={c.status} />
                    </td>
                    <td className="font-mono text-xs">
                      {c.is_synthetic ? (
                        <span className="border border-[#4A3728] bg-[#211812] px-1.5 py-0.5 text-[10px] text-aegis-copper uppercase font-semibold">
                          SYNTHETIC DEMO
                        </span>
                      ) : (
                        <span className="border border-aegis-border bg-aegis-card px-1.5 py-0.5 text-[10px] text-aegis-text-muted uppercase">
                          {c.source_type}
                        </span>
                      )}
                    </td>
                    <td>{renderSlaBadge(c.response_due_by)}</td>
                    <td className="font-mono text-xs text-aegis-text-muted tabular-nums">
                      {c.evidence_ids?.length || 0} ITEMS
                    </td>
                    <td className="font-mono text-xs text-aegis-text-muted tabular-nums">
                      {formatIsoDateTime(c.updated_at)}
                    </td>
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-lg border border-aegis-border bg-aegis-surface p-6 shadow-panel rounded-sm">
            <div className="flex items-center justify-between border-b border-aegis-border pb-3">
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                  DISPUTE INGESTION
                </span>
                <h2 id="create-dispute-modal-title" className="text-sm font-semibold text-aegis-text-primary mt-0.5">
                  Open New Dispute Case
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="text-aegis-text-muted hover:text-aegis-text-primary font-mono text-sm"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateCase} className="mt-4 space-y-4 font-mono text-xs">
              <div>
                <label htmlFor="case-source-type" className="block uppercase text-aegis-text-muted">
                  Source Type
                </label>
                <select
                  id="case-source-type"
                  value={newSourceType}
                  onChange={(e) =>
                    setNewSourceType(e.target.value as "PAYPAL_SANDBOX" | "SYNTHETIC_DEMO" | "MANUAL")
                  }
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                >
                  <option value="PAYPAL_SANDBOX">PAYPAL_SANDBOX (PayPal Dispute Ingestion)</option>
                  <option value="MANUAL">MANUAL (Direct Merchant / Support Dispute)</option>
                  <option value="SYNTHETIC_DEMO">SYNTHETIC_DEMO (Sandbox Demo Only)</option>
                </select>
              </div>

              <div>
                <label htmlFor="case-payment-intent" className="block uppercase text-aegis-text-muted">
                  Payment Intent ID <span className="text-aegis-accent">*</span>
                </label>
                <div className="mt-1.5 flex gap-2">
                  <input
                    id="case-payment-intent"
                    type="text"
                    value={newPaymentIntentId}
                    onChange={(e) => setNewPaymentIntentId(e.target.value)}
                    placeholder="Enter PaymentIntent UUID..."
                    className="flex-1 border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
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
                      className="border border-aegis-border bg-aegis-card px-2 text-aegis-text-muted focus:outline-none"
                    >
                      <option value="">PICK INTENT…</option>
                      {payments.map((p) => (
                        <option key={p.id} value={p.id} className="bg-aegis-surface">
                          {truncateId(p.id, 10)} [{p.state}]
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              </div>

              <div>
                <label htmlFor="case-reason" className="block uppercase text-aegis-text-muted">
                  Dispute Reason Code
                </label>
                <input
                  id="case-reason"
                  type="text"
                  required
                  value={newReason}
                  onChange={(e) => setNewReason(e.target.value)}
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="case-amount" className="block uppercase text-aegis-text-muted">
                    Claim Amount ({newCurrency})
                  </label>
                  <input
                    id="case-amount"
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={newAmountUsd}
                    onChange={(e) => setNewAmountUsd(e.target.value)}
                    className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary tabular-nums focus:border-aegis-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="case-paypal-id" className="block uppercase text-aegis-text-muted">
                    PayPal Dispute ID (optional)
                  </label>
                  <input
                    id="case-paypal-id"
                    type="text"
                    value={newPaypalDisputeId}
                    onChange={(e) => setNewPaypalDisputeId(e.target.value)}
                    placeholder="PP-D-XXXX"
                    className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="case-buyer-claim" className="block uppercase text-aegis-text-muted">
                  Buyer Narrative / Claim Details
                </label>
                <textarea
                  id="case-buyer-claim"
                  rows={3}
                  value={newBuyerClaim}
                  onChange={(e) => setNewBuyerClaim(e.target.value)}
                  placeholder="Buyer alleges service was not delivered or quote tampered..."
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-2.5 pt-3 border-t border-aegis-border">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="border border-aegis-border bg-aegis-card px-3.5 py-1.5 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingCase}
                  className="border border-aegis-accent bg-aegis-accent px-4 py-1.5 font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50"
                >
                  {creatingCase ? "Creating…" : "Create Dispute Case"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppShell>
  );
}
