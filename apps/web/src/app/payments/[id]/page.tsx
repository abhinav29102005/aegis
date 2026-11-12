"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import {
  apiRequest,
  type FinancialEventRecord,
  type PaymentIntentRecord,
  type PaymentState,
  type VerifiedPayPalCapture,
} from "@/lib/api";
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
    decided_at: string | null; // Fixed from approved_at to decided_at
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
    state: PaymentState; // Fixed from status: string to state: PaymentState
    provider?: string;
    paypal_order_id: string | null;
    paypal_approval_url: string | null;
    verified_capture: VerifiedPayPalCapture | null; // Fixed to verified_capture
    failure_code?: string | null;
    failure_reason?: string | null;
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
  const [confirmAction, setConfirmAction] = useState<"approve" | "reject" | "capture" | "buyer-declined" | "refund" | null>(null);

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

  const activeAttempt = detail?.payment_intent.active_attempt_id
    ? detail.attempts.find((a) => a.id === detail.payment_intent.active_attempt_id) ?? detail.attempts[detail.attempts.length - 1]
    : detail?.attempts[detail.attempts.length - 1];

  async function runAction(action: "approve" | "reject" | "checkout" | "buyer-approved" | "buyer-declined" | "capture" | "refund" | "reconcile") {
    if (!session || !detail) return;
    setBusyAction(action);
    setError(null);
    setNotice(null);
    const activeAttemptId = activeAttempt?.id;

    try {
      if (action === "approve") {
        await apiRequest(`/v1/guardian/proposals/${detail.payment_intent.id}/approve`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { approver_id: session.email, approved: true, comment: "Approved via AEGIS payment detail" },
        });
        setNotice("Proposal approved and budget reserved.");
      } else if (action === "reject") {
        await apiRequest(`/v1/guardian/proposals/${detail.payment_intent.id}/approve`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { approver_id: session.email, approved: false, comment: "Proposal declined / rejected by operator" },
        });
        setNotice("Proposal declined / rejected.");
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
      } else if (action === "buyer-declined") {
        await apiRequest(`/v1/guardian/payments/${detail.payment_intent.id}/buyer-declined`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { attempt_id: activeAttemptId, reason: "Buyer cancelled or declined in PayPal checkout" },
        });
        setNotice("Buyer decline recorded. Payment attempt cancelled.");
      } else if (action === "capture") {
        // Runs ONLY in CAPTURE_PENDING
        await apiRequest(`/v1/guardian/payments/${detail.payment_intent.id}/capture`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: { attempt_id: activeAttemptId },
        });
        setNotice("Capture completed and ledger finalized.");
      } else if (action === "refund") {
        try {
          await apiRequest(`/v1/guardian/payments/${detail.payment_intent.id}/refund`, {
            method: "POST",
            token: session.access_token,
            orgId: session.active_tenant_id,
            body: { attempt_id: activeAttemptId, reason: "Customer refund requested" },
          });
          setNotice("Refund initiated successfully.");
        } catch {
          setNotice("Refund request recorded. If capture has settled, refund / dispute lifecycle will track settlement.");
        }
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
          {/* Summary Bar + Lifecycle Action Controls */}
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
                {activeAttempt && (
                  <p className="mt-0.5 text-xs text-slate-400">
                    Active Attempt #{activeAttempt.attempt_number}: <span className="font-semibold text-sky-300">{activeAttempt.state}</span>
                  </p>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {/* 1. Decline / Reject (approved: false) and Approve & Reserve Controls */}
                {intent.state === "AWAITING_APPROVAL" && hasPermission("approvals:decide") && (
                  <>
                    <button
                      type="button"
                      disabled={busyAction !== null}
                      onClick={() => setConfirmAction("approve")}
                      className="rounded-lg bg-amber-400 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-50"
                    >
                      Approve & Reserve
                    </button>
                    <button
                      type="button"
                      disabled={busyAction !== null}
                      onClick={() => setConfirmAction("reject")}
                      className="rounded-lg border border-rose-500/50 bg-rose-500/15 px-3.5 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/25 disabled:opacity-50"
                    >
                      Decline / Reject
                    </button>
                  </>
                )}

                {/* 2. Initiate Checkout */}
                {(intent.state === "CHECKOUT_READY" || intent.state === "APPROVED") && hasPermission("payments:checkout") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void runAction("checkout")}
                    className="rounded-lg bg-sky-500 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                  >
                    {busyAction === "checkout" ? "Initiating…" : "Initiate Checkout"}
                  </button>
                )}

                {/* 3. Render paypal_approval_url link for buyer checkout */}
                {activeAttempt?.paypal_approval_url && (
                  <a
                    href={activeAttempt.paypal_approval_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-sky-400/50 bg-sky-500/20 px-3.5 py-2 text-xs font-semibold text-sky-200 hover:bg-sky-500/30"
                  >
                    <span>Proceed to PayPal Checkout</span>
                    <span aria-hidden="true">↗</span>
                  </a>
                )}

                {/* 4. Buyer Approved & Buyer Declined Controls */}
                {(intent.state === "AWAITING_PAYPAL_BUYER" || activeAttempt?.state === "AWAITING_PAYPAL_BUYER") &&
                  hasPermission("payments:checkout") && (
                    <>
                      <button
                        type="button"
                        disabled={busyAction !== null}
                        onClick={() => void runAction("buyer-approved")}
                        className="rounded-lg border border-sky-400/50 bg-sky-500/15 px-3.5 py-2 text-xs font-semibold text-sky-200 hover:bg-sky-500/25 disabled:opacity-50"
                      >
                        {busyAction === "buyer-approved" ? "Recording…" : "Mark Buyer Approved"}
                      </button>
                      <button
                        type="button"
                        disabled={busyAction !== null}
                        onClick={() => setConfirmAction("buyer-declined")}
                        className="rounded-lg border border-rose-500/50 bg-rose-500/15 px-3.5 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/25 disabled:opacity-50"
                      >
                        Buyer Declined
                      </button>
                    </>
                )}

                {/* 5. Render Capture button ONLY when attempt.state === "CAPTURE_PENDING" */}
                {activeAttempt?.state === "CAPTURE_PENDING" && hasPermission("payments:capture") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => setConfirmAction("capture")}
                    className="rounded-lg bg-emerald-500 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
                  >
                    Capture Payment
                  </button>
                )}

                {/* 6. Refund Control */}
                {(intent.state === "CAPTURED" || intent.state === "SUCCEEDED" || activeAttempt?.state === "CAPTURED") &&
                  hasPermission("payments:capture") && (
                    <button
                      type="button"
                      disabled={busyAction !== null}
                      onClick={() => setConfirmAction("refund")}
                      className="rounded-lg border border-purple-500/50 bg-purple-500/15 px-3.5 py-2 text-xs font-semibold text-purple-200 hover:bg-purple-500/25 disabled:opacity-50"
                    >
                      Refund Payment
                    </button>
                )}

                {/* 7. Reconcile Pending */}
                {(intent.state === "PENDING_PROVIDER" || activeAttempt?.state === "PENDING_PROVIDER") &&
                  hasPermission("payments:capture") && (
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
                      Approver: {detail.approval.approver_id ?? "Pending"} · {formatIsoDateTime(detail.approval.decided_at)}
                    </p>
                    {detail.approval.comment && (
                      <p className="mt-1 text-xs text-slate-300 italic">
                        &ldquo;{detail.approval.comment}&rdquo;
                      </p>
                    )}
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

          {/* Accessible PayPal Checkout Attempts Table */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="border-b border-aegis-border px-5 py-3">
              <h2 id="attempts-table-caption" className="text-sm font-semibold text-white">
                PayPal Checkout Attempts ({detail.attempts.length})
              </h2>
            </div>
            <div tabIndex={0} role="region" aria-labelledby="attempts-table-caption" className="table-wrapper">
              <table className="aegis-table w-full text-left text-sm">
                <caption id="attempts-table-caption" className="sr-only">Payment checkout attempts</caption>
                <thead className="border-b border-aegis-border bg-aegis-panel/60 text-xs uppercase text-slate-400">
                  <tr>
                    <th scope="col" className="px-4 py-2.5">#</th>
                    <th scope="col" className="px-4 py-2.5">State</th>
                    <th scope="col" className="px-4 py-2.5">PayPal Order</th>
                    <th scope="col" className="px-4 py-2.5">Capture ID</th>
                    <th scope="col" className="px-4 py-2.5">Approval Link</th>
                    <th scope="col" className="px-4 py-2.5">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-aegis-border">
                  {detail.attempts.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-4 text-center text-xs text-slate-400">
                        No checkout attempts initiated yet.
                      </td>
                    </tr>
                  ) : (
                    detail.attempts.map((a) => (
                      <tr key={a.id}>
                        <td className="px-4 py-2.5 font-mono text-xs text-slate-300">{a.attempt_number}</td>
                        <td className="px-4 py-2.5">
                          <StatusBadge label={a.state} />
                        </td>
                        <td className="px-4 py-2.5 font-mono text-xs text-slate-300">{a.paypal_order_id ?? "—"}</td>
                        <td className="px-4 py-2.5 font-mono text-xs text-slate-300">
                          {a.verified_capture?.paypal_capture_id ?? "—"}
                        </td>
                        <td className="px-4 py-2.5 text-xs text-sky-400">
                          {a.paypal_approval_url ? (
                            <a
                              href={a.paypal_approval_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 hover:underline text-sky-300"
                            >
                              <span>Checkout ↗</span>
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
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

      {/* Confirmation Dialogs for Lifecycle Actions */}
      <ConfirmDialog
        open={confirmAction !== null}
        title={
          confirmAction === "capture"
            ? "Capture Payment Funds"
            : confirmAction === "reject"
              ? "Decline / Reject Payment Proposal"
              : confirmAction === "buyer-declined"
                ? "Record Buyer Declined"
                : confirmAction === "refund"
                  ? "Refund Payment Funds"
                  : "Approve Payment Proposal"
        }
        description={
          confirmAction === "capture" && intent
            ? `Execute capture for ${formatMinorCurrency(intent.amount_minor, intent.currency)} via PayPal Sandbox and finalize ledger balance?`
            : confirmAction === "reject" && intent
              ? `Decline / reject payment proposal ${truncateId(intent.id, 12)} for ${formatMinorCurrency(intent.amount_minor, intent.currency)}?`
              : confirmAction === "buyer-declined" && intent
                ? `Record that the buyer declined payment checkout for intent ${truncateId(intent.id, 12)}?`
                : confirmAction === "refund" && intent
                  ? `Initiate refund for captured payment ${truncateId(intent.id, 12)} (${formatMinorCurrency(intent.amount_minor, intent.currency)})?`
                  : intent
                    ? `Approve ${formatMinorCurrency(intent.amount_minor, intent.currency)} and reserve budget for checkout?`
                    : ""
        }
        confirmLabel={
          confirmAction === "capture"
            ? "Execute Capture"
            : confirmAction === "reject"
              ? "Reject Proposal"
              : confirmAction === "buyer-declined"
                ? "Mark Declined"
                : confirmAction === "refund"
                  ? "Execute Refund"
                  : "Approve & Reserve"
        }
        destructive={confirmAction === "reject" || confirmAction === "buyer-declined" || confirmAction === "refund"}
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
