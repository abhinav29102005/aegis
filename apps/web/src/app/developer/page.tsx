"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, truncateId } from "@/lib/format";

interface ApiKeyRow {
  id: string;
  name: string;
  key_prefix: string;
  role: string;
  status: string;
  created_at: string;
}

interface WebhookEndpointRow {
  id: string;
  url: string;
  description: string;
  event_types: string[];
  status: string;
  created_at: string;
}

interface OutboxRow {
  id: string;
  event_type: string;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
}

export default function DeveloperPortalPage() {
  const { session, hasPermission } = useAuth();
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [endpoints, setEndpoints] = useState<WebhookEndpointRow[]>([]);
  const [outbox, setOutbox] = useState<OutboxRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [revealedSecret, setRevealedSecret] = useState<{ label: string; value: string } | null>(null);
  const [keyName, setKeyName] = useState("ci-agent-runtime");
  const [keyRole, setKeyRole] = useState("DEVELOPER");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookDesc, setWebhookDesc] = useState("Production billing listener");

  const [confirmKeyAction, setConfirmKeyAction] = useState<{ type: "rotate" | "revoke"; key: ApiKeyRow } | null>(null);
  const [busy, setBusy] = useState(false);

  const loadData = useCallback(async () => {
    if (!session) return;
    setError(null);
    try {
      const requests: Promise<unknown>[] = [
        hasPermission("keys:manage")
          ? apiRequest<ApiKeyRow[]>("/v1/orgs/api-keys", {
              token: session.access_token,
              orgId: session.active_tenant_id,
            })
          : Promise.resolve([]),
        hasPermission("webhooks:manage")
          ? apiRequest<WebhookEndpointRow[]>("/v1/webhooks/endpoints", {
              token: session.access_token,
              orgId: session.active_tenant_id,
            })
          : Promise.resolve([]),
        hasPermission("audit:read")
          ? apiRequest<OutboxRow[]>("/v1/worker/outbox?limit=30", {
              token: session.access_token,
              orgId: session.active_tenant_id,
            })
          : Promise.resolve([]),
      ];
      const [k, w, o] = (await Promise.all(requests)) as [ApiKeyRow[], WebhookEndpointRow[], OutboxRow[]];
      setKeys(k);
      setEndpoints(w);
      setOutbox(o);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load developer settings");
    }
  }, [hasPermission, session]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleCreateApiKey(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiRequest<{ id: string; name: string; plaintext_key: string }>("/v1/orgs/api-keys", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { name: keyName.trim(), role: keyRole },
      });
      setRevealedSecret({ label: `API Key "${created.name}"`, value: created.plaintext_key });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to issue API key");
    } finally {
      setBusy(false);
    }
  }

  async function handleKeyAction() {
    if (!session || !confirmKeyAction) return;
    setBusy(true);
    setError(null);
    try {
      if (confirmKeyAction.type === "rotate") {
        const res = await apiRequest<{ plaintext_key: string }>(
          `/v1/orgs/api-keys/${confirmKeyAction.key.id}/rotate`,
          {
            method: "POST",
            token: session.access_token,
            orgId: session.active_tenant_id,
          },
        );
        setRevealedSecret({ label: `Rotated Key "${confirmKeyAction.key.name}"`, value: res.plaintext_key });
      } else {
        await apiRequest(`/v1/orgs/api-keys/${confirmKeyAction.key.id}/revoke`, {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
        });
      }
      setConfirmKeyAction(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "API key operation failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateWebhook(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiRequest<{ url: string; signing_secret: string }>("/v1/webhooks/endpoints", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { url: webhookUrl.trim(), description: webhookDesc.trim(), event_types: ["*"] },
      });
      setRevealedSecret({ label: `Webhook Secret (${created.url})`, value: created.signing_secret });
      setWebhookUrl("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register webhook endpoint");
    } finally {
      setBusy(false);
    }
  }

  async function handleRequeue(outboxId: string) {
    if (!session) return;
    setError(null);
    try {
      await apiRequest(`/v1/worker/outbox/${outboxId}/requeue`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to requeue outbox item");
    }
  }

  return (
    <AppShell
      title="Developer Portal"
      subtitle="Issue scoped API keys (`aegis_<env>_...`), configure HMAC-signed webhooks, and inspect background worker outbox health."
    >
      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {revealedSecret && (
        <div role="status" className="mb-6 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-amber-200">
              One-Time Secret — {revealedSecret.label} (copied value will never be shown again)
            </span>
            <button
              type="button"
              onClick={() => setRevealedSecret(null)}
              className="text-xs text-amber-200 underline"
            >
              Dismiss
            </button>
          </div>
          <code className="mt-2 block break-all rounded-lg border border-amber-500/30 bg-slate-950/70 px-3 py-2 font-mono text-xs text-amber-100">
            {revealedSecret.value}
          </code>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* API Keys */}
        <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
          <h2 className="text-sm font-semibold text-white">Organization API Keys</h2>
          {hasPermission("keys:manage") && (
            <form onSubmit={handleCreateApiKey} className="mt-3 flex flex-wrap gap-2">
              <input
                type="text"
                required
                aria-label="API key name"
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
                className="min-w-[160px] flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs text-white"
              />
              <select
                aria-label="API key role"
                value={keyRole}
                onChange={(e) => setKeyRole(e.target.value)}
                className="rounded-lg border border-aegis-border bg-aegis-panel px-2.5 py-1.5 text-xs text-white"
              >
                <option value="DEVELOPER">DEVELOPER</option>
                <option value="AGENT_RUNTIME">AGENT_RUNTIME</option>
                <option value="FINANCE_ADMIN">FINANCE_ADMIN</option>
                <option value="VIEWER">VIEWER</option>
              </select>
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400"
              >
                Issue Key
              </button>
            </form>
          )}

          <div className="mt-4 space-y-2 text-xs">
            {keys.map((k) => (
              <div key={k.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-aegis-border bg-aegis-panel p-3">
                <div>
                  <div className="font-semibold text-white">{k.name}</div>
                  <div className="font-mono text-[11px] text-slate-400">
                    {k.key_prefix}… · {k.role} · {formatIsoDateTime(k.created_at)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge label={k.status} />
                  {k.status === "ACTIVE" && hasPermission("keys:manage") && (
                    <>
                      <button
                        type="button"
                        onClick={() => setConfirmKeyAction({ type: "rotate", key: k })}
                        className="rounded border border-aegis-border px-2 py-1 text-[11px] text-slate-200 hover:bg-slate-800"
                      >
                        Rotate
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmKeyAction({ type: "revoke", key: k })}
                        className="rounded border border-rose-500/40 px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-500/10"
                      >
                        Revoke
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Webhooks */}
        <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
          <h2 className="text-sm font-semibold text-white">Signed Outbound Webhooks</h2>
          {hasPermission("webhooks:manage") && (
            <form onSubmit={handleCreateWebhook} className="mt-3 space-y-2">
              <input
                type="url"
                required
                aria-label="Webhook URL"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://hooks.yourcompany.com/aegis"
                className="w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs text-white"
              />
              <div className="flex gap-2">
                <input
                  type="text"
                  aria-label="Webhook description"
                  value={webhookDesc}
                  onChange={(e) => setWebhookDesc(e.target.value)}
                  className="flex-1 rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs text-white"
                />
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400"
                >
                  Add Endpoint
                </button>
              </div>
            </form>
          )}

          <div className="mt-4 space-y-2 text-xs">
            {endpoints.length === 0 ? (
              <p className="text-slate-400">No webhook endpoints registered.</p>
            ) : (
              endpoints.map((ep) => (
                <div key={ep.id} className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="break-all font-mono text-sky-300">{ep.url}</span>
                    <StatusBadge label={ep.status} />
                  </div>
                  <p className="mt-1 text-slate-400">{ep.description || "All events"}</p>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* Transactional Outbox */}
      <section className="mt-6 rounded-xl border border-aegis-border bg-aegis-surface">
        <div className="border-b border-aegis-border px-5 py-3">
          <h2 className="text-sm font-semibold text-white">Worker Transactional Outbox ({outbox.length})</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Transactional outbox queue</caption>
            <thead className="border-b border-aegis-border bg-aegis-panel/60 uppercase text-slate-400">
              <tr>
                <th className="px-4 py-2.5">Outbox ID</th>
                <th className="px-4 py-2.5">Event Type</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Attempts</th>
                <th className="px-4 py-2.5">Last Error</th>
                <th className="px-4 py-2.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-aegis-border">
              {outbox.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-5 text-center text-slate-400">
                    Outbox queue is empty.
                  </td>
                </tr>
              ) : (
                outbox.map((row) => (
                  <tr key={row.id}>
                    <td className="px-4 py-2.5 font-mono text-slate-300">{truncateId(row.id, 10)}</td>
                    <td className="px-4 py-2.5 font-medium text-white">{row.event_type}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge label={row.status} />
                    </td>
                    <td className="px-4 py-2.5 text-slate-300">{row.attempts}</td>
                    <td className="px-4 py-2.5 text-slate-400">{row.last_error ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right">
                      {row.status === "DEAD_LETTER" && hasPermission("worker:manage") && (
                        <button
                          type="button"
                          onClick={() => void handleRequeue(row.id)}
                          className="rounded border border-sky-500/40 px-2.5 py-1 text-[11px] text-sky-300 hover:bg-sky-500/10"
                        >
                          Requeue
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmDialog
        open={confirmKeyAction !== null}
        title={confirmKeyAction?.type === "rotate" ? "Rotate API Key" : "Revoke API Key"}
        description={
          confirmKeyAction?.type === "rotate"
            ? `Revoke old secret for "${confirmKeyAction.key.name}" and issue a fresh plaintext key immediately?`
            : confirmKeyAction
              ? `Permanently revoke "${confirmKeyAction.key.name}" (${confirmKeyAction.key.key_prefix}…)? Active agents using it will fail authentication.`
              : ""
        }
        confirmLabel={confirmKeyAction?.type === "rotate" ? "Rotate Secret" : "Revoke Key"}
        destructive={confirmKeyAction?.type === "revoke"}
        busy={busy}
        onCancel={() => setConfirmKeyAction(null)}
        onConfirm={() => void handleKeyAction()}
      />
    </AppShell>
  );
}
