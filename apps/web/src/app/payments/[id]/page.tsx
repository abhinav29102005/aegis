"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type FinancialEventRecord, type PaymentIntentRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

interface PaymentDetailPayload {
  payment_intent: PaymentIntentRecord;
  proposal: {
    id: string;
    merchant_name: string;
    merchant_category: string;
    item_summary: string;
    rationale: string;
    amount_minor: number;
    currency: string;
  } | null;
  quote: {
    id: string;
    quote_hash: string;
    expires_at: string;
  } | null;
  decision: {
    id: string;
    outcome: string;
    policy_version: string;
    reason_codes: string[];
    decided_at: string;
  } | null;
  approval: {
    id: string;
    status: string;
    approver_id: string | null;
    approved_at: string | null;
    comment: string | null;
  } | null;
  reservation: {
    id: string;
    amount_minor: number;
    currency: string;
    status: string;
  } | null;
  attempts: Array<{
    id: string;
    attempt_number: number;
    status: string;
    paypal_order_id: string | null;
    paypal_capture_id: string | null;
    paypal_approval_url: string | null;
    created_at: string;
  }>;
  events: FinancialEventRecord[];
}

export default function PaymentDetailPage() {
  const params = useParams<{ id: string }>();
  const intentId = params?.id ?? "";
  const { session, hasPermission } = useAuth();
  const [detail, setDetail] = useState<PaymentDetailPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<"approve" | "capture" | null>(null);

  const loadDetail = useCallback(async () => {
    if (!session || !intentId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest<PaymentDetailPayload>(`/v1/guardian/payments/${intentId}/detail`, {
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load payment detail");
    } finally {
      setLoading(false);
    }
  }, [intentId, session]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  async function runAction(action: "approve" | "checkout" | "buyer-approved" | "capture" | "reconcile") {
    if (!session || !detail) return;
    setBusyAction(action);
    setError(null);
    setNotice(null);
    const activeAttemptId = detail.payment_intent.active_attempt_id ?? detail.attempts[detail.attempts.length - 1]?.id;

    try {
      if (action === "approve") {
        await apiRequest(`/v1/guardian/proposals/${detail.payment_intent.id}/approve`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { approver_id: session.email, approved: true, comment: "Approved via AEGIS payment detail" },
        });
        setNotice("Proposal approved and budget reserved.");
      } else if (action === "checkout") {
        await apiRequest(`/v1/guardian/payments/${detail.payment_intent.id}/checkout`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: {
            attempt_number: detail.attempts.length + 1,
            idempotency_key: `checkout-${crypto.randomUUID()}`,
          },
        });
        setNotice("PayPal sandbox checkout initiated.");
      } else if (action === "buyer-approved") {
        await apiRequest(`/v1/guardian/payments/${detail.payment_intent.id}/buyer-approved`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { attempt_id: activeAttemptId, payer_id: "SANDBOX_PAYER_WEB" },
        });
        setNotice("Buyer approval recorded for active attempt.");
      } else if (action === "capture") {
        await apiRequest(`/v1/guardian/payments/${detail.payment_intent.id}/capture`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { attempt_id: activeAttemptId },
        });
        setNotice("Capture completed and ledger finalized.");
      } else if (action === "reconcile") {
        await apiRequest(`/v1/guardian/payments/${detail.payment_intent.id}/reconcile`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { attempt_id: activeAttemptId },
        });
        setNotice("Provider status reconciled.");
      }
      setConfirmAction(null);
      await loadDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to run ${action}`);
    } finally {
      setBusyAction(null);
    }
  }

  const intent = detail?.payment_intent;

  return (
    <AppShell title="Payment Lifecycle & Evidence" subtitle={intent ? `Intent ${intent.id}` : "Loading payment intent..."}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Link href="/payments" className="text-xs font-medium text-sky-400 hover:underline">
          ← Back to Payments
        </Link>
        {intent && (
          <Link
            href={`/ghostpay/replay/${intent.id}`}
            className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-300 hover:bg-sky-500/20"
          >
            Open in GhostPay Replay →
          </Link>
        )}
      </div>

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

      {loading || !detail || !intent ? (
        <div className="rounded-xl border border-aegis-border bg-aegis-surface p-6 text-sm text-slate-400">
          Loading payment lifecycle…
        </div>
      ) : (
        <div className="space-y-6">
          {/* Summary Bar + Controls */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <StatusBadge label={intent.state} />
                  <span className="text-2xl font-bold text-white">
                    {formatMinorCurrency(intent.amount_minor, intent.currency)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  Correlation: <span className="font-mono text-slate-300">{intent.correlation_id}</span>
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                {intent.state === "AWAITING_APPROVAL" && hasPermission("approvals:decide") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => setConfirmAction("approve")}
                    className="rounded-lg bg-amber-400 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-50"
                  >
                    Approve & Reserve
                  </button>
                )}
                {intent.state === "CHECKOUT_READY" && hasPermission("payments:checkout") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void runAction("checkout")}
                    className="rounded-lg bg-sky-500 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                  >
                    {busyAction === "checkout" ? "Initiating…" : "Initiate Checkout"}
                  </button>
                )}
                {intent.state === "AWAITING_PAYPAL_BUYER" && hasPermission("payments:checkout") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void runAction("buyer-approved")}
                    className="rounded-lg border border-sky-400/50 bg-sky-500/15 px-3.5 py-2 text-xs font-semibold text-sky-200 hover:bg-sky-500/25 disabled:opacity-50"
                  >
                    {busyAction === "buyer-approved" ? "Recording…" : "Mark Buyer Approved"}
                  </button>
                )}
                {intent.state === "BUYER_APPROVED" && hasPermission("payments:capture") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => setConfirmAction("capture")}
                    className="rounded-lg bg-emerald-500 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
                  >
                    Capture Payment
                  </button>
                )}
                {intent.state === "PENDING_PROVIDER" && hasPermission("payments:capture") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void runAction("reconcile")}
                    className="rounded-lg border border-amber-400/50 bg-amber-500/15 px-3.5 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
                  >
                    Reconcile Pending
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* Evidence & Governance Grid */}
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Proposal & Immutable Quote</h2>
              {detail.proposal ? (
                <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt className="text-slate-400">Merchant</dt>
                    <dd className="mt-0.5 font-medium text-white">{detail.proposal.merchant_name}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-400">Category</dt>
                    <dd className="mt-0.5 font-medium text-white">{detail.proposal.merchant_category}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-slate-400">Item Summary</dt>
                    <dd className="mt-0.5 text-slate-200">{detail.proposal.item_summary}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-slate-400">Rationale</dt>
                    <dd className="mt-0.5 text-slate-300">{detail.proposal.rationale}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-slate-400">Quote SHA-256</dt>
                    <dd className="mt-0.5 break-all font-mono text-[11px] text-slate-300">{intent.quote_hash}</dd>
                  </div>
                </dl>
              ) : (
                <p className="mt-2 text-xs text-slate-400">Proposal snapshot unavailable.</p>
              )}
            </section>

            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Policy Decision, Approval & Reservation</h2>
              <div className="mt-3 space-y-3 text-xs">
                {detail.decision && (
                  <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-200">Policy Outcome ({detail.decision.policy_version})</span>
                      <StatusBadge label={detail.decision.outcome} />
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {detail.decision.reason_codes.map((rc) => (
                        <span key={rc} className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-300">
                          {rc}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {detail.approval && (
                  <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-200">Human Approval</span>
                      <StatusBadge label={detail.approval.status} />
                    </div>
                    <p className="mt-1 text-slate-400">
                      Approver: {detail.approval.approver_id ?? "Pending"} · {formatIsoDateTime(detail.approval.approved_at)}
                    </p>
                  </div>
                )}
                {detail.reservation && (
                  <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-200">Budget Reservation</span>
                      <StatusBadge label={detail.reservation.status} />
                    </div>
                    <p className="mt-1 text-slate-300">
                      {formatMinorCurrency(detail.reservation.amount_minor, detail.reservation.currency)}
                    </p>
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* Checkout Attempts */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="border-b border-aegis-border px-5 py-3">
              <h2 className="text-sm font-semibold text-white">PayPal Checkout Attempts ({detail.attempts.length})</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Payment checkout attempts</caption>
                <thead className="border-b border-aegis-border bg-aegis-panel/60 text-xs uppercase text-slate-400">
                  <tr>
                    <th className="px-4 py-2.5">#</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">PayPal Order</th>
                    <th className="px-4 py-2.5">Capture ID</th>
                    <th className="px-4 py-2.5">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-aegis-border">
                  {detail.attempts.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-4 text-center text-xs text-slate-400">
                        No checkout attempts initiated yet.
                      </td>
                    </tr>
                  ) : (
                    detail.attempts.map((a) => (
                      <tr key={a.id}>
                        <td className="px-4 py-2.5 font-mono text-xs text-slate-300">{a.attempt_number}</td>
                        <td className="px-4 py-2.5">
                          <StatusBadge label={a.status} />
                        </td>
                        <td className="px-4 py-2.5 font-mono text-xs text-slate-300">{a.paypal_order_id ?? "—"}</td>
                        <td className="px-4 py-2.5 font-mono text-xs text-slate-300">{a.paypal_capture_id ?? "—"}</td>
                        <td className="px-4 py-2.5 text-xs text-slate-400">{formatIsoDateTime(a.created_at)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* Financial Event Timeline */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="border-b border-aegis-border px-5 py-3">
              <h2 className="text-sm font-semibold text-white">Hash-Chained Financial Events ({detail.events.length})</h2>
            </div>
            <div className="divide-y divide-aegis-border">
              {detail.events.map((ev) => (
                <div key={ev.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-xs">
                  <div>
                    <span className="font-mono text-slate-400">#{ev.sequence_number}</span>{" "}
                    <span className="font-semibold text-white">{ev.event_type}</span>{" "}
                    <span className="text-slate-400">by {ev.actor_id}</span>
                  </div>
                  <div className="font-mono text-[11px] text-slate-400">
                    hash: {truncateId(ev.event_hash, 16)} · {formatIsoDateTime(ev.occurred_at)}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      <ConfirmDialog
        open={confirmAction !== null}
        title={confirmAction === "capture" ? "Capture Payment Funds" : "Approve Payment Proposal"}
        description={
          confirmAction === "capture" && intent
            ? `Capture ${formatMinorCurrency(intent.amount_minor, intent.currency)} via PayPal Sandbox and finalize spent ledger balance?`
            : intent
              ? `Approve ${formatMinorCurrency(intent.amount_minor, intent.currency)} and reserve budget for checkout?`
              : ""
        }
        confirmLabel={confirmAction === "capture" ? "Execute Capture" : "Approve & Reserve"}
        busy={busyAction !== null}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => {
          if (confirmAction) {
            void runAction(confirmAction);
          }
        }}
      />
    </AppShell>
  );
}
