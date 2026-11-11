"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, getApiBaseUrl, type DisputeCaseRecord } from "@/lib/api";
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
  latest_analysis: {
    id: string;
    summary: string;
    recommendation: string;
    draft_response_text: string;
    contradictions: Array<{ code: string; severity: string; summary: string }>;
    evidence_citations: Array<{ evidence_id: string; claim: string }>;
    missing_evidence: string[];
    model_used: string | null;
    analyzed_at: string;
  } | null;
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

  const [busy, setBusy] = useState(false);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false);

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

  const dc = detail?.case;

  return (
    <AppShell title="Dispute Case Dossier" subtitle={dc ? `Case ${dc.id}` : "Loading dispute case..."}>
      <div className="mb-4 flex items-center justify-between">
        <Link href="/disputes" className="text-xs font-medium text-sky-400 hover:underline">
          ← Back to Dispute Cases
        </Link>
        {dc && (
          <Link href={`/payments/${dc.payment_intent_id}`} className="text-xs font-medium text-slate-300 hover:underline">
            Inspect Linked Payment →
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

          {/* Header Summary */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge label={dc.status} />
                  {dc.is_synthetic && <StatusBadge label="SYNTHETIC_DEMO" />}
                  <span className="text-xl font-bold text-white">
                    {formatMinorCurrency(dc.amount_minor, dc.currency)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-200">{dc.buyer_claim}</p>
                <p className="mt-1 text-xs text-slate-400">Reason: {dc.reason}</p>
              </div>
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
          </section>

          {/* Grounded AI Analysis & Human Approval */}
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Grounded Analysis & Contradictions</h2>
              {detail.latest_analysis ? (
                <div className="mt-3 space-y-3 text-xs">
                  <p className="text-slate-200">{detail.latest_analysis.summary}</p>
                  <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                    <div className="font-semibold text-slate-300">
                      Recommendation: {detail.latest_analysis.recommendation}
                    </div>
                    <div className="mt-1 text-slate-400">
                      Engine: {detail.latest_analysis.model_used ?? "Deterministic evidence analyzer"}
                    </div>
                  </div>
                  {detail.latest_analysis.contradictions.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-amber-200">Detected Contradictions</h3>
                      <ul className="mt-1 space-y-1.5">
                        {detail.latest_analysis.contradictions.map((c) => (
                          <li key={c.code} className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-amber-100">
                            <span className="font-mono font-semibold">{c.code}</span> ({c.severity}): {c.summary}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="text-slate-400">
                    Evidence graph: {detail.evidence_graph.nodes.length} nodes · {detail.evidence_graph.edges.length} edges
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs text-slate-400">Run Grounded Analysis to build citations and detect contradictions.</p>
              )}
            </section>

            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Human-Reviewed Dispute Response</h2>
              <label htmlFor="draft-response" className="mt-2 block text-xs text-slate-400">
                Edit and verify every cited fact before human sign-off.
              </label>
              <textarea
                id="draft-response"
                rows={7}
                value={draftResponse}
                onChange={(e) => setDraftResponse(e.target.value)}
                className="mt-2 w-full rounded-lg border border-aegis-border bg-aegis-panel p-3 text-xs text-slate-100"
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
                    disabled={busy || dc.is_synthetic || !dc.human_approved_for_submission || dc.status === "SUBMITTED"}
                    onClick={() => setConfirmSubmit(true)}
                    title={dc.is_synthetic ? "Synthetic demo cases cannot be submitted externally" : undefined}
                    className="rounded-lg bg-emerald-500 px-3.5 py-2 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-40"
                  >
                    {dc.status === "SUBMITTED" ? "Submitted" : "Submit to PayPal"}
                  </button>
                )}
              </div>
            </section>
          </div>

          {/* Evidence & Artifacts */}
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Evidence Records & Uploaded Artifacts</h2>
              {hasPermission("disputes:write") && (
                <form onSubmit={handleUploadArtifact} className="mt-3 space-y-2 rounded-lg border border-aegis-border bg-aegis-panel p-3">
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
                    Upload Artifact
                  </button>
                </form>
              )}

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

      <ConfirmDialog
        open={confirmApprove}
        title="Approve Dispute Response Draft"
        description="Seal the edited response text with a SHA-256 hash and mark this case APPROVED_FOR_SUBMISSION?"
        confirmLabel="Approve Draft"
        busy={busy}
        onCancel={() => setConfirmApprove(false)}
        onConfirm={() => void handleApproveDraft()}
      />

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
    </AppShell>
  );
}
