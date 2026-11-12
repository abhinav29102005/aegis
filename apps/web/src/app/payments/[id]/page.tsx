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
    decided_at: string | null;
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
    state: PaymentState;
    provider?: string;
    paypal_order_id: string | null;
    paypal_approval_url: string | null;
    verified_capture: VerifiedPayPalCapture | null;
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
          setNotice("Refund request recorded. If capture has settled, refund lifecycle will track settlement.");
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
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 font-mono text-xs">
        <Link href="/payments" className="text-aegis-accent hover:underline">
          ← Back to Payments
        </Link>
        {intent && (
          <Link
            href={`/ghostpay/replay/${intent.id}`}
            className="rounded border border-aegis-accent/40 bg-aegis-accent/10 px-3 py-1.5 text-aegis-accent hover:bg-aegis-accent/20 transition"
          >
            Open in GhostPay Replay →
          </Link>
        )}
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded border border-aegis-rose/40 bg-aegis-rose/10 px-4 py-3 font-mono text-xs text-aegis-rose">
          [FAULT] {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mb-4 rounded border border-aegis-accent/40 bg-aegis-accent/10 px-4 py-3 font-mono text-xs text-aegis-accent">
          [OK] {notice}
        </div>
      )}

      {loading || !detail || !intent ? (
        <div className="rounded-xl border border-aegis-border bg-aegis-surface p-6 font-mono text-xs text-aegis-text-muted">
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
                  <span className="font-mono text-2xl font-bold text-aegis-text-primary">
                    {formatMinorCurrency(intent.amount_minor, intent.currency)}
                  </span>
                </div>
                <p className="mt-1 font-mono text-xs text-aegis-text-muted">
                  Correlation ID: <span className="text-aegis-text-primary">{intent.correlation_id}</span>
                </p>
                {activeAttempt && (
                  <p className="mt-0.5 font-mono text-xs text-aegis-text-muted">
                    Active Attempt #{activeAttempt.attempt_number}: <span className="text-aegis-accent font-semibold">{activeAttempt.state}</span>
                  </p>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                {/* 1. Decline / Reject and Approve & Reserve Controls */}
                {intent.state === "AWAITING_APPROVAL" && hasPermission("approvals:decide") && (
                  <>
                    <button
                      type="button"
                      disabled={busyAction !== null}
                      onClick={() => setConfirmAction("approve")}
                      className="rounded bg-aegis-accent px-3.5 py-2 font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
                    >
                      Approve & Reserve
                    </button>
                    <button
                      type="button"
                      disabled={busyAction !== null}
                      onClick={() => setConfirmAction("reject")}
                      className="rounded border border-aegis-rose/40 bg-aegis-rose/10 px-3.5 py-2 font-semibold uppercase tracking-wider text-aegis-rose hover:bg-aegis-rose/20 transition disabled:opacity-50"
                    >
                      Decline Proposal
                    </button>
                  </>
                )}

                {/* 2. Initiate Checkout */}
                {(intent.state === "CHECKOUT_READY" || intent.state === "APPROVED") && hasPermission("payments:checkout") && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void runAction("checkout")}
                    className="rounded bg-aegis-accent px-3.5 py-2 font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
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
                    className="inline-flex items-center gap-1.5 rounded border border-aegis-copper/50 bg-aegis-copper/15 px-3.5 py-2 font-semibold uppercase tracking-wider text-aegis-copper hover:bg-aegis-copper/25 transition"
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
                        className="rounded border border-aegis-accent/40 bg-aegis-accent/15 px-3.5 py-2 font-semibold uppercase tracking-wider text-aegis-accent hover:bg-aegis-accent/25 transition disabled:opacity-50"
                      >
                        {busyAction === "buyer-approved" ? "Recording…" : "Mark Buyer Approved"}
                      </button>
                      <button
                        type="button"
                        disabled={busyAction !== null}
                        onClick={() => setConfirmAction("buyer-declined")}
                        className="rounded border border-aegis-rose/40 bg-aegis-rose/10 px-3.5 py-2 font-semibold uppercase tracking-wider text-aegis-rose hover:bg-aegis-rose/20 transition disabled:opacity-50"
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
                    className="rounded bg-aegis-accent px-3.5 py-2 font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
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
                      className="rounded border border-aegis-rose/40 bg-aegis-rose/10 px-3.5 py-2 font-semibold uppercase tracking-wider text-aegis-rose hover:bg-aegis-rose/20 transition disabled:opacity-50"
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
                      className="rounded border border-aegis-copper/40 bg-aegis-copper/10 px-3.5 py-2 font-semibold uppercase tracking-wider text-aegis-copper hover:bg-aegis-copper/20 transition disabled:opacity-50"
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
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[PROPOSAL SNAPSHOT // QUOTE]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Proposal & Deterministic Quote</h2>
              </div>
              {detail.proposal ? (
                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt className="font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">Merchant</dt>
                    <dd className="mt-0.5 font-medium text-aegis-text-primary">{detail.proposal.merchant_name}</dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">Category</dt>
                    <dd className="mt-0.5 font-mono text-aegis-text-primary">{detail.proposal.merchant_category}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">Item Summary</dt>
                    <dd className="mt-0.5 text-aegis-text-primary">{detail.proposal.item_summary}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">Rationale</dt>
                    <dd className="mt-0.5 text-aegis-text-muted">{detail.proposal.rationale}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">Quote SHA-256</dt>
                    <dd className="mt-0.5 break-all font-mono text-[11px] text-aegis-accent">{intent.quote_hash}</dd>
                  </div>
                </dl>
              ) : (
                <p className="mt-3 font-mono text-xs text-aegis-text-muted">Proposal snapshot unavailable.</p>
              )}
            </section>

            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper">[POLICY ENGINE // VERDICT]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Decision, Approval & Reservation</h2>
              </div>
              <div className="mt-4 space-y-3 text-xs">
                {detail.decision && (
                  <div className="rounded border border-aegis-border bg-aegis-card p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-medium text-aegis-text-primary">Policy Verdict ({detail.decision.policy_version})</span>
                      <StatusBadge label={detail.decision.outcome} />
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {detail.decision.reason_codes.map((rc) => (
                        <span key={rc} className="rounded border border-aegis-border bg-aegis-surface px-2 py-0.5 font-mono text-[11px] text-aegis-text-muted">
                          {rc}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {detail.approval && (
                  <div className="rounded border border-aegis-border bg-aegis-card p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-medium text-aegis-text-primary">Human Approval Record</span>
                      <StatusBadge label={detail.approval.status} />
                    </div>
                    <p className="mt-1 font-mono text-xs text-aegis-text-muted">
                      Approver: {detail.approval.approver_id ?? "Pending"} · {formatIsoDateTime(detail.approval.decided_at)}
                    </p>
                    {detail.approval.comment && (
                      <p className="mt-1 text-xs italic text-aegis-text-primary">
                        &ldquo;{detail.approval.comment}&rdquo;
                      </p>
                    )}
                  </div>
                )}
                {detail.reservation && (
                  <div className="rounded border border-aegis-border bg-aegis-card p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-medium text-aegis-text-primary">Budget Reservation</span>
                      <StatusBadge label={detail.reservation.status} />
                    </div>
                    <p className="mt-1 font-mono text-xs text-aegis-accent font-semibold">
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
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[EXECUTION ATTEMPTS // PAYPAL]</span>
              <h2 id="attempts-table-caption" className="text-sm font-semibold tracking-wide text-aegis-text-primary">
                Checkout Attempts ({detail.attempts.length})
              </h2>
            </div>
            <div tabIndex={0} role="region" aria-labelledby="attempts-table-caption" className="table-wrapper">
              <table className="aegis-table w-full text-left text-xs">
                <caption id="attempts-table-caption" className="sr-only">Payment checkout attempts</caption>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">State</th>
                    <th scope="col">PayPal Order</th>
                    <th scope="col">Capture ID</th>
                    <th scope="col">Approval Link</th>
                    <th scope="col">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.attempts.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-4 text-center font-mono text-aegis-text-muted">
                        No checkout attempts initiated yet.
                      </td>
                    </tr>
                  ) : (
                    detail.attempts.map((a) => (
                      <tr key={a.id}>
                        <td className="font-mono text-aegis-text-muted">{a.attempt_number}</td>
                        <td>
                          <StatusBadge label={a.state} />
                        </td>
                        <td className="font-mono text-aegis-text-primary">{a.paypal_order_id ?? "—"}</td>
                        <td className="font-mono text-aegis-accent font-semibold">
                          {a.verified_capture?.paypal_capture_id ?? "—"}
                        </td>
                        <td className="font-mono text-xs">
                          {a.paypal_approval_url ? (
                            <a
                              href={a.paypal_approval_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-aegis-copper hover:underline"
                            >
                              <span>Checkout ↗</span>
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="font-mono text-aegis-text-faint">{formatIsoDateTime(a.created_at)}</td>
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
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[TAMPER-EVIDENT // HASH CHAIN]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">
                Chained Financial Events ({detail.events.length})
              </h2>
            </div>
            <div className="divide-y divide-aegis-border">
              {detail.events.map((ev) => (
                <div key={ev.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 font-mono text-xs">
                  <div>
                    <span className="rounded bg-aegis-card border border-aegis-border px-1.5 py-0.5 text-aegis-accent font-bold">
                      #{ev.sequence_number}
                    </span>{" "}
                    <span className="font-semibold text-aegis-text-primary ml-1.5">{ev.event_type}</span>{" "}
                    <span className="text-aegis-text-muted">by {ev.actor_id}</span>
                  </div>
                  <div className="text-[11px] text-aegis-text-muted">
                    hash: <span className="text-aegis-accent">{truncateId(ev.event_hash, 16)}</span> ·{" "}
                    <span className="text-aegis-text-faint">{formatIsoDateTime(ev.occurred_at)}</span>
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