"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import {
  apiRequest,
  getApiBaseUrl,
  type DisputeAnalysis,
  type DisputeCaseRecord,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

interface CaseDetailPayload {
  case: DisputeCaseRecord;
  evidence: Array<{
    id: string;
    source_type: string;
    source_ref: string;
    title: string;
    content: Record<string, unknown>;
    content_hash: string;
    is_synthetic: boolean;
    ingested_at: string;
  }>;
  latest_analysis: DisputeAnalysis | null;
  evidence_graph: {
    nodes: Array<{ id: string; node_type: string; label: string }>;
    edges: Array<{ source_id: string; target_id: string; relation: string }>;
  };
  assigned_to: string | null;
  notes: Array<{ author: string; body: string; created_at: string }>;
  artifacts: Array<{
    id: string;
    evidence_record_id: string;
    filename: string;
    content_type: string;
    byte_size: number;
    sha256: string;
    created_at: string;
  }>;
}

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
        SLA OVERDUE ({overdueHrs}h)
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
      title={`Response due by: ${formatIsoDateTime(dueIso)}`}
    >
      <span>⏱</span> Response SLA: {days > 0 ? `${days}d ${remainingHours}h` : `${hours}h`} remaining
    </span>
  );
}

export default function DisputeCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const caseId = params?.id ?? "";
  const { session, hasPermission } = useAuth();

  const [detail, setDetail] = useState<CaseDetailPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [assignee, setAssignee] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [artifactTitle, setArtifactTitle] = useState("Signed Carrier Receipt");
  const [artifactFile, setArtifactFile] = useState<File | null>(null);
  const [draftResponse, setDraftResponse] = useState("");

  // JSON /evidence attach form state
  const [showJsonEvidenceForm, setShowJsonEvidenceForm] = useState(false);
  const [jsonEvidenceTitle, setJsonEvidenceTitle] = useState("Carrier Delivery Confirmation");
  const [jsonEvidenceSourceType, setJsonEvidenceSourceType] = useState("DELIVERY_RECEIPT");
  const [jsonEvidenceSourceRef, setJsonEvidenceSourceRef] = useState("fedex:track:920559012345");
  const [jsonEvidenceRaw, setJsonEvidenceRaw] = useState(
    JSON.stringify(
      {
        tracking_number: "920559012345",
        status: "DELIVERED",
        delivered_at: "2026-11-10T14:32:00Z",
        signed_by: "FRONT_PORCH",
        latitude: 37.7749,
        longitude: -122.4194,
      },
      null,
      2,
    ),
  );

  // Modals & Action busy states
  const [busy, setBusy] = useState(false);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [confirmResolve, setConfirmResolve] = useState(false);
  const [resolveReason, setResolveReason] = useState("Resolved in merchant favor via signed delivery evidence.");
  const [exportingReport, setExportingReport] = useState(false);

  const loadCase = useCallback(async () => {
    if (!session || !caseId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest<CaseDetailPayload>(`/v1/disputeos/cases/${caseId}`, {
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setDetail(data);
      setAssignee(data.assigned_to ?? session.email);
      setDraftResponse(data.latest_analysis?.draft_response_text ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dispute case");
    } finally {
      setLoading(false);
    }
  }, [caseId, session]);

  useEffect(() => {
    void loadCase();
  }, [loadCase]);

  async function handleAssign(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !caseId) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/v1/disputeos/cases/${caseId}/assign`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { assigned_to: assignee.trim() },
      });
      setNotice(`Assigned case to ${assignee.trim()}.`);
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign case");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddNote(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !caseId || !noteBody.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/v1/disputeos/cases/${caseId}/notes`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { body: noteBody.trim() },
      });
      setNoteBody("");
      setNotice("Analyst note added.");
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add analyst note");
    } finally {
      setBusy(false);
    }
  }

  async function handleAttachJsonEvidence(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !caseId) return;
    let parsedContent: Record<string, unknown>;
    try {
      parsedContent = JSON.parse(jsonEvidenceRaw);
    } catch {
      setError("Invalid JSON entered. Please check formatting.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/v1/disputeos/cases/${caseId}/evidence`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          title: jsonEvidenceTitle.trim() || "Structured Evidence Document",
          source_type: jsonEvidenceSourceType,
          source_ref: jsonEvidenceSourceRef.trim() || "manual:evidence",
          content: parsedContent,
          is_synthetic: detail?.case.is_synthetic ?? false,
        },
      });
      setNotice("Structured JSON evidence attached with content hash.");
      setShowJsonEvidenceForm(false);
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to attach JSON evidence");
    } finally {
      setBusy(false);
    }
  }

  async function handleUploadArtifact(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !caseId || !artifactFile) return;
    setBusy(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", artifactFile);
      formData.append("title", artifactTitle.trim() || artifactFile.name);
      formData.append("source_type", "DELIVERY_RECEIPT");
      await apiRequest(`/v1/disputeos/cases/${caseId}/artifacts`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: formData,
        isFormData: true,
      });
      setArtifactFile(null);
      setNotice("Artifact uploaded with SHA-256 hash verification.");
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Artifact upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDownloadArtifact(artifactId: string, filename: string) {
    if (!session || !caseId) return;
    setError(null);
    try {
      const resp = await fetch(`${getApiBaseUrl()}/v1/disputeos/cases/${caseId}/artifacts/${artifactId}`, {
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          "X-Org-Id": session.active_tenant_id,
        },
      });
      if (!resp.ok) {
        throw new Error(`Download failed (HTTP ${resp.status})`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download artifact");
    }
  }

  async function handleAnalyze() {
    if (!session || !caseId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(`/v1/disputeos/cases/${caseId}/analyze`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setNotice("Grounded dispute analysis & contradiction check completed.");
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dispute analysis failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleApproveDraft() {
    if (!session || !caseId || !draftResponse.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/v1/disputeos/cases/${caseId}/approve`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          approver_id: session.email,
          draft_response_text: draftResponse.trim(),
        },
      });
      setConfirmApprove(false);
      setNotice("Draft response human-approved and SHA-256 sealed.");
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitExternal() {
    if (!session || !caseId) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/v1/disputeos/cases/${caseId}/submit`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {},
      });
      setConfirmSubmit(false);
      setNotice("Dispute response submitted to PayPal Sandbox.");
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "External submission failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleResolveCase() {
    if (!session || !caseId) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/v1/disputeos/cases/${caseId}/resolve`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { reason: resolveReason.trim() },
      });
      setConfirmResolve(false);
      setNotice("Dispute case marked as RESOLVED.");
      await loadCase();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve dispute case");
    } finally {
      setBusy(false);
    }
  }

  async function handleExportReport() {
    if (!session || !caseId) return;
    setExportingReport(true);
    setError(null);
    try {
      const report = await apiRequest<Record<string, unknown>>(`/v1/disputeos/cases/${caseId}/report`, {
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `dispute-report-${caseId}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setNotice("Dossier report downloaded successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export dispute report");
    } finally {
      setExportingReport(false);
    }
  }

  const dc = detail?.case;
  const analysis = detail?.latest_analysis;

  return (
    <AppShell title="Dispute Case Dossier" subtitle={dc ? `Case ${dc.id}` : "Loading dispute case..."}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Link href="/disputes" className="text-xs font-medium text-sky-400 hover:underline">
          ← Back to Dispute Cases
        </Link>
        <div className="flex items-center gap-3">
          {dc && (
            <Link href={`/payments/${dc.payment_intent_id}`} className="text-xs font-medium text-slate-300 hover:underline">
              Inspect Linked Payment →
            </Link>
          )}
        </div>
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

      {loading || !detail || !dc ? (
        <div className="rounded-xl border border-aegis-border bg-aegis-surface p-6 text-sm text-slate-400">
          Loading dispute dossier…
        </div>
      ) : (
        <div className="space-y-6">
          {dc.is_synthetic && (
            <div className="rounded-xl border border-sky-500/40 bg-sky-500/10 px-4 py-3 text-xs text-sky-200">
              <strong>SYNTHETIC DEMO RECORD:</strong> This case was generated from sandbox test fixtures and is permanently blocked from external PayPal submission (`SyntheticSubmissionError`).
            </div>
          )}

          {/* Header Summary & Actions Bar */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge label={dc.status} />
                  {dc.is_synthetic ? (
                    <StatusBadge label="SYNTHETIC_DEMO" />
                  ) : (
                    <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                      {dc.source_type}
                    </span>
                  )}
                  {renderSlaBadge(dc.response_due_by)}
                  <span className="text-xl font-bold text-white">
                    {formatMinorCurrency(dc.amount_minor, dc.currency)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-200">{dc.buyer_claim}</p>
                <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-slate-400">
                  <span>Reason: <strong className="text-slate-200">{dc.reason}</strong></span>
                  {dc.paypal_dispute_id && (
                    <span>PayPal Dispute ID: <strong className="font-mono text-sky-300">{dc.paypal_dispute_id}</strong></span>
                  )}
                  <span>Opened: {formatIsoDateTime(dc.opened_at)}</span>
                  {dc.response_due_by && (
                    <span>Due: <strong className="text-slate-300">{formatIsoDateTime(dc.response_due_by)}</strong></span>
                  )}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={exportingReport}
                  onClick={() => void handleExportReport()}
                  className="rounded-lg border border-aegis-border bg-aegis-panel px-3.5 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                >
                  {exportingReport ? "Exporting…" : "Export Report"}
                </button>

                {hasPermission("disputes:write") && dc.status !== "RESOLVED" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setConfirmResolve(true)}
                    className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3.5 py-2 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    Resolve Case
                  </button>
                )}

                {hasPermission("disputes:write") && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void handleAnalyze()}
                    className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                  >
                    {busy ? "Analyzing…" : "Run Grounded Analysis"}
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* Grounded AI Analysis & Human Approval */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Grounded Analysis Card */}
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Grounded Analysis & Contradictions</h2>
                {analysis && (
                  <span
                    className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                      analysis.generated_with_llm
                        ? "border border-purple-500/40 bg-purple-500/10 text-purple-300"
                        : "border border-sky-500/40 bg-sky-500/10 text-sky-300"
                    }`}
                  >
                    {analysis.generated_with_llm ? "LLM Augmented" : "Deterministic Engine"}
                  </span>
                )}
              </div>

              {analysis ? (
                <div className="mt-3 space-y-4 text-xs">
                  {/* Grounded Summary */}
                  <div>
                    <h3 className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                      Grounded Summary
                    </h3>
                    <p className="mt-1 leading-relaxed text-slate-200">{analysis.grounded_summary}</p>
                  </div>

                  {/* Recommendation & Confidence */}
                  <div className="grid grid-cols-2 gap-3 rounded-lg border border-aegis-border bg-aegis-panel p-3">
                    <div>
                      <div className="text-[11px] uppercase text-slate-400">Recommendation</div>
                      <div className="mt-1 font-semibold text-white">{analysis.recommendation}</div>
                    </div>
                    <div>
                      <div className="text-[11px] uppercase text-slate-400">Confidence Score</div>
                      <div className="mt-1 font-mono font-semibold text-sky-300">
                        {Math.round(analysis.confidence_score * 100)}%
                      </div>
                    </div>
                  </div>

                  {/* Agent Authorization & Compliance Flags */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded px-2 py-0.5 text-[11px] ${analysis.agent_authorized ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/30" : "bg-rose-500/10 text-rose-300 border border-rose-500/30"}`}>
                      Agent Authorized: {analysis.agent_authorized ? "Yes" : "No"}
                    </span>
                    <span className={`rounded px-2 py-0.5 text-[11px] ${analysis.agent_followed_policy ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/30" : "bg-rose-500/10 text-rose-300 border border-rose-500/30"}`}>
                      Policy Compliant: {analysis.agent_followed_policy ? "Yes" : "No"}
                    </span>
                  </div>

                  {/* Contradictions */}
                  {analysis.contradictions && analysis.contradictions.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-amber-200">
                        Detected Contradictions ({analysis.contradictions.length})
                      </h3>
                      <ul className="mt-1.5 space-y-1.5">
                        {analysis.contradictions.map((c, idx) => (
                          <li
                            key={idx}
                            className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-amber-100"
                          >
                            {typeof c === "string" ? c : JSON.stringify(c)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Missing Evidence */}
                  {analysis.missing_evidence && analysis.missing_evidence.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-rose-300">
                        Missing Evidence ({analysis.missing_evidence.length})
                      </h3>
                      <ul className="mt-1.5 space-y-1">
                        {analysis.missing_evidence.map((me, idx) => (
                          <li
                            key={idx}
                            className="rounded border border-rose-500/30 bg-rose-500/10 px-2.5 py-1.5 text-rose-200"
                          >
                            {me}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Recommended Actions */}
                  {analysis.recommended_actions && analysis.recommended_actions.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-sky-200">
                        Recommended Actions ({analysis.recommended_actions.length})
                      </h3>
                      <ul className="mt-1.5 space-y-1">
                        {analysis.recommended_actions.map((act, idx) => (
                          <li
                            key={idx}
                            className="flex items-center gap-2 rounded border border-sky-500/30 bg-sky-500/10 px-2.5 py-1.5 text-sky-100"
                          >
                            <span className="text-sky-400">→</span> {act}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Citations */}
                  {analysis.citations && analysis.citations.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-slate-300">
                        Evidence Citations ({analysis.citations.length})
                      </h3>
                      <ul className="mt-1.5 space-y-2">
                        {analysis.citations.map((cite, idx) => (
                          <li
                            key={idx}
                            className="rounded-lg border border-aegis-border bg-aegis-panel p-2.5 text-slate-300"
                          >
                            <div className="flex items-center justify-between">
                              <span className="font-medium text-white">{cite.claim}</span>
                              <span className={`text-[10px] ${cite.verified ? "text-emerald-400" : "text-amber-400"}`}>
                                {cite.verified ? "✓ Verified" : "Unverified"}
                              </span>
                            </div>
                            {cite.verbatim_excerpt && (
                              <blockquote className="mt-1 border-l-2 border-sky-500/40 pl-2 text-[11px] italic text-slate-400">
                                &ldquo;{cite.verbatim_excerpt}&rdquo;
                              </blockquote>
                            )}
                            <div className="mt-1 font-mono text-[10px] text-slate-500">
                              Ref: {truncateId(cite.evidence_id, 14)}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="text-[11px] text-slate-400">
                    Evidence graph: {detail.evidence_graph.nodes.length} nodes · {detail.evidence_graph.edges.length} edges
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs text-slate-400">
                  Run Grounded Analysis to build verifiable citations and detect contradictions across all records.
                </p>
              )}
            </section>

            {/* Human-Reviewed Dispute Response */}
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Human-Reviewed Dispute Response</h2>
              <label htmlFor="draft-response" className="mt-2 block text-xs text-slate-400">
                Edit and verify every cited fact before human sign-off. Response is sealed with a SHA-256 hash.
              </label>
              <textarea
                id="draft-response"
                rows={9}
                value={draftResponse}
                onChange={(e) => setDraftResponse(e.target.value)}
                className="mt-2 w-full rounded-lg border border-aegis-border bg-aegis-panel p-3 text-xs leading-relaxed text-slate-100"
                placeholder="Run analysis or compose verified dispute response..."
              />
              <div className="mt-3 flex flex-wrap gap-2">
                {hasPermission("disputes:approve") && (
                  <button
                    type="button"
                    disabled={busy || !draftResponse.trim()}
                    onClick={() => setConfirmApprove(true)}
                    className="rounded-lg bg-amber-400 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-50"
                  >
                    Approve Draft for Submission
                  </button>
                )}
                {hasPermission("disputes:submit") && (
                  <button
                    type="button"
                    disabled={
                      busy ||
                      dc.is_synthetic ||
                      !dc.human_approved_for_submission ||
                      dc.status === "SUBMITTED" ||
                      dc.status === "RESOLVED"
                    }
                    onClick={() => setConfirmSubmit(true)}
                    title={
                      dc.is_synthetic
                        ? "Synthetic demo cases cannot be submitted externally"
                        : !dc.human_approved_for_submission
                          ? "Must be approved first"
                          : undefined
                    }
                    className="rounded-lg bg-emerald-500 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-40"
                  >
                    {dc.status === "SUBMITTED" ? "Submitted" : "Submit to PayPal"}
                  </button>
                )}
              </div>
            </section>
          </div>

          {/* Evidence Records, JSON Evidence & Uploaded Artifacts */}
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Evidence Records & Artifacts</h2>
                {hasPermission("disputes:write") && (
                  <button
                    type="button"
                    onClick={() => setShowJsonEvidenceForm((s) => !s)}
                    className="rounded border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 text-xs font-medium text-sky-300 hover:bg-sky-500/20"
                  >
                    {showJsonEvidenceForm ? "Close JSON Form" : "+ Attach JSON Evidence"}
                  </button>
                )}
              </div>

              {/* JSON /evidence attach form */}
              {showJsonEvidenceForm && (
                <form
                  onSubmit={handleAttachJsonEvidence}
                  className="mt-3 space-y-3 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 text-xs"
                >
                  <h3 className="font-semibold text-sky-200">Attach Structured JSON Evidence</h3>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div>
                      <label htmlFor="json-ev-title" className="block text-slate-300">Title</label>
                      <input
                        id="json-ev-title"
                        type="text"
                        value={jsonEvidenceTitle}
                        onChange={(e) => setJsonEvidenceTitle(e.target.value)}
                        className="mt-1 w-full rounded border border-aegis-border bg-aegis-panel px-2.5 py-1.5 text-white"
                      />
                    </div>
                    <div>
                      <label htmlFor="json-ev-type" className="block text-slate-300">Source Type</label>
                      <select
                        id="json-ev-type"
                        value={jsonEvidenceSourceType}
                        onChange={(e) => setJsonEvidenceSourceType(e.target.value)}
                        className="mt-1 w-full rounded border border-aegis-border bg-aegis-panel px-2.5 py-1.5 text-white"
                      >
                        <option value="DELIVERY_RECEIPT">DELIVERY_RECEIPT</option>
                        <option value="CARRIER_TRACKING">CARRIER_TRACKING</option>
                        <option value="CUSTOMER_MESSAGE">CUSTOMER_MESSAGE</option>
                        <option value="PAYPAL_ORDER">PAYPAL_ORDER</option>
                        <option value="PAYPAL_CAPTURE">PAYPAL_CAPTURE</option>
                        <option value="PAYPAL_WEBHOOK">PAYPAL_WEBHOOK</option>
                        <option value="POLICY_DECISION">POLICY_DECISION</option>
                        <option value="HUMAN_APPROVAL">HUMAN_APPROVAL</option>
                        <option value="SYNTHETIC_FIXTURE">SYNTHETIC_FIXTURE</option>
                      </select>
                    </div>
                  </div>
                  <div>
                    <label htmlFor="json-ev-ref" className="block text-slate-300">Source Reference</label>
                    <input
                      id="json-ev-ref"
                      type="text"
                      value={jsonEvidenceSourceRef}
                      onChange={(e) => setJsonEvidenceSourceRef(e.target.value)}
                      placeholder="e.g. carrier:tracking:12345"
                      className="mt-1 w-full rounded border border-aegis-border bg-aegis-panel px-2.5 py-1.5 font-mono text-white"
                    />
                  </div>
                  <div>
                    <label htmlFor="json-ev-content" className="block text-slate-300">JSON Payload</label>
                    <textarea
                      id="json-ev-content"
                      rows={5}
                      value={jsonEvidenceRaw}
                      onChange={(e) => setJsonEvidenceRaw(e.target.value)}
                      className="mt-1 w-full rounded border border-aegis-border bg-aegis-panel p-2 font-mono text-[11px] text-white"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded bg-sky-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                  >
                    {busy ? "Attaching…" : "Save Evidence Record"}
                  </button>
                </form>
              )}

              {/* File Artifact Upload Form */}
              {hasPermission("disputes:write") && (
                <form
                  onSubmit={handleUploadArtifact}
                  className="mt-3 space-y-2 rounded-lg border border-aegis-border bg-aegis-panel p-3"
                >
                  <div className="grid gap-2 sm:grid-cols-2">
                    <input
                      type="text"
                      aria-label="Artifact title"
                      value={artifactTitle}
                      onChange={(e) => setArtifactTitle(e.target.value)}
                      className="rounded-lg border border-aegis-border bg-aegis-surface px-2.5 py-1.5 text-xs text-white"
                      placeholder="Document title"
                    />
                    <input
                      type="file"
                      aria-label="Evidence artifact file"
                      onChange={(e) => setArtifactFile(e.target.files?.[0] ?? null)}
                      className="text-xs text-slate-300"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy || !artifactFile}
                    className="rounded-md bg-sky-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                  >
                    Upload File Artifact
                  </button>
                </form>
              )}

              {/* Evidence Records List */}
              <ul className="mt-3 space-y-2 text-xs">
                {detail.evidence.map((ev) => {
                  const matchedArt = detail.artifacts.find((a) => a.evidence_record_id === ev.id);
                  return (
                    <li key={ev.id} className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-white">{ev.title}</span>
                        <StatusBadge label={ev.source_type} />
                      </div>
                      <p className="mt-1 font-mono text-[11px] text-slate-400">
                        SHA-256: {truncateId(ev.content_hash, 18)}
                      </p>
                      {matchedArt && (
                        <button
                          type="button"
                          onClick={() => void handleDownloadArtifact(matchedArt.id, matchedArt.filename)}
                          className="mt-2 rounded border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 text-[11px] font-medium text-sky-300 hover:bg-sky-500/20"
                        >
                          Download {matchedArt.filename} ({matchedArt.byte_size} bytes)
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>

            {/* Assignment & Analyst Notes */}
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Assignment & Investigation Notes</h2>
              <form onSubmit={handleAssign} className="mt-3 flex gap-2">
                <input
                  type="text"
                  aria-label="Case assignee"
                  value={assignee}
                  onChange={(e) => setAssignee(e.target.value)}
                  className="flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs text-white"
                  placeholder="analyst@company.com"
                />
                <button
                  type="submit"
                  disabled={busy || !hasPermission("disputes:write")}
                  className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                >
                  Assign
                </button>
              </form>

              <form onSubmit={handleAddNote} className="mt-3 flex gap-2">
                <input
                  type="text"
                  aria-label="Investigation note"
                  value={noteBody}
                  onChange={(e) => setNoteBody(e.target.value)}
                  className="flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs text-white"
                  placeholder="Add verification note..."
                />
                <button
                  type="submit"
                  disabled={busy || !noteBody.trim() || !hasPermission("disputes:write")}
                  className="rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                >
                  Add Note
                </button>
              </form>

              <div className="mt-3 space-y-2 text-xs">
                {detail.notes.length === 0 ? (
                  <p className="text-slate-400">No analyst notes yet.</p>
                ) : (
                  detail.notes.map((n, idx) => (
                    <div key={`${n.created_at}-${idx}`} className="rounded-lg border border-aegis-border bg-aegis-panel p-2.5">
                      <div className="flex justify-between text-[11px] text-slate-400">
                        <span>{n.author}</span>
                        <span>{formatIsoDateTime(n.created_at)}</span>
                      </div>
                      <p className="mt-1 text-slate-200">{n.body}</p>
                    </div>
                  ))
                )}
              </div>
            </section>
          </div>
        </div>
      )}

      {/* Approval Confirmation Dialog */}
      <ConfirmDialog
        open={confirmApprove}
        title="Approve Dispute Response Draft"
        description="Seal the edited response text with a SHA-256 hash and mark this case APPROVED_FOR_SUBMISSION?"
        confirmLabel="Approve Draft"
        busy={busy}
        onCancel={() => setConfirmApprove(false)}
        onConfirm={() => void handleApproveDraft()}
      />

      {/* PayPal External Submission Confirmation Dialog */}
      <ConfirmDialog
        open={confirmSubmit}
        title="Submit Dispute Response to PayPal"
        description="Transmit the human-approved dispute response to PayPal Sandbox? This records an irreversible submission event."
        confirmLabel="Submit Externally"
        destructive
        busy={busy}
        onCancel={() => setConfirmSubmit(false)}
        onConfirm={() => void handleSubmitExternal()}
      />

      {/* Resolve Case Modal / Dialog */}
      {confirmResolve && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="resolve-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4"
        >
          <div className="w-full max-w-md rounded-2xl border border-aegis-border bg-aegis-surface p-6 shadow-2xl">
            <h2 id="resolve-modal-title" className="text-base font-semibold text-white">
              Resolve Dispute Case
            </h2>
            <p className="mt-1 text-xs text-slate-400">
              Close this dispute case and transition status to <span className="font-semibold text-emerald-400">RESOLVED</span> via <span className="font-mono text-sky-300">POST /v1/disputeos/cases/{caseId}/resolve</span>.
            </p>
            <div className="mt-4">
              <label htmlFor="resolve-reason-input" className="block text-xs font-medium text-slate-300">
                Resolution Notes
              </label>
              <textarea
                id="resolve-reason-input"
                rows={3}
                value={resolveReason}
                onChange={(e) => setResolveReason(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel p-2.5 text-xs text-white"
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirmResolve(false)}
                className="rounded-lg border border-aegis-border px-3.5 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleResolveCase()}
                className="rounded-lg bg-emerald-500 px-4 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
              >
                {busy ? "Resolving…" : "Confirm Resolution"}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
