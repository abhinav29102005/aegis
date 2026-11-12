"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Bot,
  Key,
  Layers,
  Radio,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, CANONICAL_ROLES, type Role } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, truncateId } from "@/lib/format";

interface ApiKeyRow {
  id: string;
  name: string;
  key_prefix: string;
  role: Role;
  status: string;
  created_at: string;
}

interface ServiceAccountRow {
  id: string;
  name: string;
  description: string;
  role: Role;
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

interface WebhookDeliveryRow {
  id: string;
  endpoint_id: string;
  event_type: string;
  status: string;
  attempts: number;
  response_status: number | null;
  last_error: string | null;
  delivered_at: string | null;
  created_at: string;
}

interface OutboxRow {
  id: string;
  aggregate_type?: string;
  aggregate_id?: string;
  event_type: string;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
}

export default function DeveloperPortalPage() {
  const { session, hasPermission } = useAuth();

  // Tab selection
  const [activeTab, setActiveTab] = useState<"keys" | "service_accounts" | "webhooks" | "outbox">("keys");

  // Data states
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [serviceAccounts, setServiceAccounts] = useState<ServiceAccountRow[]>([]);
  const [endpoints, setEndpoints] = useState<WebhookEndpointRow[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryRow[]>([]);
  const [outbox, setOutbox] = useState<OutboxRow[]>([]);
  const [outboxFilter, setOutboxFilter] = useState<"ALL" | "DEAD_LETTER">("ALL");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Modal / input states
  const [revealedSecret, setRevealedSecret] = useState<{ label: string; value: string } | null>(null);

  // API Key creation
  const [keyName, setKeyName] = useState("ci-agent-runtime");
  const [keyRole, setKeyRole] = useState<Role>("AGENT_SERVICE");

  // Service Account creation
  const [saName, setSaName] = useState("");
  const [saDescription, setSaDescription] = useState("");
  const [saRole, setSaRole] = useState<Role>("AGENT_SERVICE");

  // Webhook creation
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookDesc, setWebhookDesc] = useState("Production billing listener");

  // Actions
  const [confirmKeyAction, setConfirmKeyAction] = useState<{ type: "rotate" | "revoke"; key: ApiKeyRow } | null>(null);
  const [confirmDeleteWebhook, setConfirmDeleteWebhook] = useState<WebhookEndpointRow | null>(null);
  const [busy, setBusy] = useState(false);

  const loadData = useCallback(async () => {
    if (!session) return;
    setError(null);
    setLoading(true);
    try {
      const requests: Promise<unknown>[] = [
        hasPermission("keys:manage")
          ? apiRequest<ApiKeyRow[]>("/v1/orgs/api-keys", {
              token: session.access_token,
              orgId: session.active_tenant_id,
            })
          : Promise.resolve([]),
        hasPermission("keys:manage")
          ? apiRequest<ServiceAccountRow[]>("/v1/orgs/service-accounts", {
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
          ? apiRequest<WebhookDeliveryRow[]>("/v1/webhooks/deliveries?limit=50", {
              token: session.access_token,
              orgId: session.active_tenant_id,
            })
          : Promise.resolve([]),
        hasPermission("audit:read")
          ? apiRequest<OutboxRow[]>(
              outboxFilter === "DEAD_LETTER"
                ? "/v1/worker/outbox?status_filter=DEAD_LETTER&limit=50"
                : "/v1/worker/outbox?limit=50",
              {
                token: session.access_token,
                orgId: session.active_tenant_id,
              },
            )
          : Promise.resolve([]),
      ];

      const [k, sa, w, del, o] = (await Promise.all(requests)) as [
        ApiKeyRow[],
        ServiceAccountRow[],
        WebhookEndpointRow[],
        WebhookDeliveryRow[],
        OutboxRow[],
      ];
      setKeys(k || []);
      setServiceAccounts(sa || []);
      setEndpoints(w || []);
      setDeliveries(del || []);
      setOutbox(o || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load developer portal records");
    } finally {
      setLoading(false);
    }
  }, [hasPermission, session, outboxFilter]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Create API Key
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
      setKeyName("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to issue API key");
    } finally {
      setBusy(false);
    }
  }

  // Key Rotate / Revoke
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

  // Create Service Account
  async function handleCreateServiceAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest("/v1/orgs/service-accounts", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          name: saName.trim(),
          description: saDescription.trim(),
          role: saRole,
        },
      });
      setSaName("");
      setSaDescription("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create service account");
    } finally {
      setBusy(false);
    }
  }

  // Create Webhook Endpoint
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
      setWebhookDesc("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register webhook endpoint");
    } finally {
      setBusy(false);
    }
  }

  // Delete Webhook Endpoint
  async function handleDeleteWebhook() {
    if (!session || !confirmDeleteWebhook) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/v1/webhooks/endpoints/${confirmDeleteWebhook.id}`, {
        method: "DELETE",
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setConfirmDeleteWebhook(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disable webhook endpoint");
    } finally {
      setBusy(false);
    }
  }

  // Requeue Worker Outbox Event
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

  const deadLetterCount = outbox.filter((o) => o.status === "DEAD_LETTER").length;

  return (
    <AppShell
      title="Developer & Worker Portal"
      subtitle="Issue scoped API keys with canonical RBAC roles, manage Service Accounts, configure HMAC webhooks, and inspect the Transactional Outbox DLQ"
    >
      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="mb-4 flex items-center gap-2.5 rounded border border-aegis-rose/40 bg-aegis-rose/10 px-4 py-3 font-mono text-xs text-aegis-rose"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-aegis-rose" />
          <span>[FAULT] {error}</span>
        </div>
      )}

      {revealedSecret && (
        <div role="status" className="mb-6 rounded border border-aegis-copper/50 bg-aegis-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-xs font-semibold uppercase tracking-wider text-aegis-copper">
              [SECRET REVEAL] {revealedSecret.label} — Copy now, value will never be displayed again
            </span>
            <button
              type="button"
              onClick={() => setRevealedSecret(null)}
              className="font-mono text-xs text-aegis-copper hover:underline"
            >
              Dismiss
            </button>
          </div>
          <code className="mt-2 block break-all rounded border border-aegis-copper/30 bg-[#111513] px-3 py-2 font-mono text-xs text-aegis-copper">
            {revealedSecret.value}
          </code>
        </div>
      )}

      {/* Tabs */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-3">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setActiveTab("keys")}
            className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 font-mono text-xs transition ${
              activeTab === "keys"
                ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
                : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
            }`}
          >
            <Key className="h-3.5 w-3.5" />
            <span>API Keys ({keys.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("service_accounts")}
            className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 font-mono text-xs transition ${
              activeTab === "service_accounts"
                ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
                : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
            }`}
          >
            <Bot className="h-3.5 w-3.5" />
            <span>Service Accounts ({serviceAccounts.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("webhooks")}
            className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 font-mono text-xs transition ${
              activeTab === "webhooks"
                ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
                : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
            }`}
          >
            <Radio className="h-3.5 w-3.5" />
            <span>Webhooks ({endpoints.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("outbox")}
            className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 font-mono text-xs transition ${
              activeTab === "outbox"
                ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
                : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
            }`}
          >
            <Layers className="h-3.5 w-3.5" />
            <span>Worker Outbox / DLQ</span>
            {deadLetterCount > 0 && (
              <span className="rounded border border-aegis-rose/40 bg-aegis-rose/20 px-1.5 py-0.2 text-[10px] font-bold text-aegis-rose">
                {deadLetterCount} DLQ
              </span>
            )}
          </button>
        </div>

        <button
          type="button"
          onClick={() => void loadData()}
          className="inline-flex items-center gap-1.5 rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary hover:bg-aegis-secondary transition"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* TAB 1: API KEYS */}
      {activeTab === "keys" && (
        <div className="grid gap-6 lg:grid-cols-3">
          {hasPermission("keys:manage") && (
            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5 lg:col-span-1">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[CREDENTIALS // PROVISION]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Issue Scoped API Key</h2>
              </div>
              <p className="mt-2 text-xs text-aegis-text-muted">
                API keys authenticate autonomous agents or microservices with strict RBAC enforcement.
              </p>
              <form onSubmit={(e) => void handleCreateApiKey(e)} className="mt-4 space-y-3">
                <div>
                  <label htmlFor="key-name-input" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Key Identifier / Name
                  </label>
                  <input
                    id="key-name-input"
                    type="text"
                    required
                    value={keyName}
                    onChange={(e) => setKeyName(e.target.value)}
                    placeholder="e.g. procurement-agent-runtime"
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="key-role-select" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Canonical Role
                  </label>
                  <select
                    id="key-role-select"
                    value={keyRole}
                    onChange={(e) => setKeyRole(e.target.value as Role)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-2.5 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  >
                    {CANONICAL_ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                  <span className="mt-1 block font-mono text-[10px] text-aegis-text-faint">
                    Recommended: <code>AGENT_SERVICE</code> for autonomous agent runtimes.
                  </span>
                </div>
                <button
                  type="submit"
                  disabled={busy}
                  className="w-full rounded bg-aegis-accent py-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
                >
                  {busy ? "Issuing Key…" : "Generate API Key"}
                </button>
              </form>
            </div>
          )}

          <div className={hasPermission("keys:manage") ? "lg:col-span-2" : "lg:col-span-3"}>
            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[ACTIVE SECRETS // DIRECTORY]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Active API Keys ({keys.length})</h2>
              </div>
              <div className="mt-4 space-y-2.5 text-xs">
                {keys.length === 0 ? (
                  <p className="py-4 text-center font-mono text-aegis-text-muted">No API keys generated yet.</p>
                ) : (
                  keys.map((k) => (
                    <div
                      key={k.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded border border-aegis-border bg-aegis-card p-3"
                    >
                      <div>
                        <div className="font-semibold text-aegis-text-primary">{k.name}</div>
                        <div className="mt-0.5 font-mono text-[11px] text-aegis-text-muted">
                          <span className="text-aegis-accent">{k.key_prefix}…</span> · Role:{" "}
                          <span className="text-aegis-text-primary font-semibold">{k.role}</span> · Created:{" "}
                          <span className="text-aegis-text-faint">{formatIsoDateTime(k.created_at)}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusBadge label={k.status} />
                        {k.status === "ACTIVE" && hasPermission("keys:manage") && (
                          <>
                            <button
                              type="button"
                              onClick={() => setConfirmKeyAction({ type: "rotate", key: k })}
                              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-[11px] text-aegis-text-primary hover:bg-aegis-secondary transition"
                            >
                              Rotate
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmKeyAction({ type: "revoke", key: k })}
                              className="rounded border border-aegis-rose/40 bg-aegis-rose/10 px-2 py-1 font-mono text-[11px] text-aegis-rose hover:bg-aegis-rose/20 transition"
                            >
                              Revoke
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: SERVICE ACCOUNTS */}
      {activeTab === "service_accounts" && (
        <div className="grid gap-6 lg:grid-cols-3">
          {hasPermission("keys:manage") && (
            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5 lg:col-span-1">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[MICROSERVICES // ACCOUNTS]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Register Service Account</h2>
              </div>
              <p className="mt-2 text-xs text-aegis-text-muted">
                Create a non-human identity for background daemons and webhook processors.
              </p>
              <form onSubmit={(e) => void handleCreateServiceAccount(e)} className="mt-4 space-y-3">
                <div>
                  <label htmlFor="sa-name-input" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Account Name
                  </label>
                  <input
                    id="sa-name-input"
                    type="text"
                    required
                    value={saName}
                    onChange={(e) => setSaName(e.target.value)}
                    placeholder="order-processor-sa"
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="sa-desc-input" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Description
                  </label>
                  <input
                    id="sa-desc-input"
                    type="text"
                    value={saDescription}
                    onChange={(e) => setSaDescription(e.target.value)}
                    placeholder="Worker daemon for payment captures"
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="sa-role-select" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Assigned Role
                  </label>
                  <select
                    id="sa-role-select"
                    value={saRole}
                    onChange={(e) => setSaRole(e.target.value as Role)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-2.5 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  >
                    {CANONICAL_ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="submit"
                  disabled={busy}
                  className="w-full rounded bg-aegis-accent py-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
                >
                  {busy ? "Creating…" : "Create Service Account"}
                </button>
              </form>
            </div>
          )}

          <div className={hasPermission("keys:manage") ? "lg:col-span-2" : "lg:col-span-3"}>
            <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[SERVICE DIRECTORY]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Configured Service Accounts ({serviceAccounts.length})</h2>
              </div>
              <div className="mt-4 space-y-2.5 text-xs">
                {serviceAccounts.length === 0 ? (
                  <p className="py-4 text-center font-mono text-aegis-text-muted">No service accounts registered.</p>
                ) : (
                  serviceAccounts.map((sa) => (
                    <div
                      key={sa.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded border border-aegis-border bg-aegis-card p-3"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-aegis-text-primary">{sa.name}</span>
                          <span className="rounded bg-aegis-surface border border-aegis-border px-1.5 py-0.5 font-mono text-[10px] text-aegis-accent">
                            {sa.role}
                          </span>
                        </div>
                        <p className="mt-1 text-aegis-text-muted">{sa.description || "No description provided."}</p>
                        <div className="mt-1 font-mono text-[10px] text-aegis-text-faint">
                          ID: {truncateId(sa.id, 12)} · Created: {formatIsoDateTime(sa.created_at)}
                        </div>
                      </div>
                      <StatusBadge label={sa.status || "ACTIVE"} />
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: WEBHOOKS & DELIVERIES */}
      {activeTab === "webhooks" && (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-3">
            {hasPermission("webhooks:manage") && (
              <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5 lg:col-span-1">
                <div className="border-b border-aegis-border pb-3">
                  <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[DISPATCH // HMAC WEBHOOK]</span>
                  <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Register Webhook Endpoint</h2>
                </div>
                <p className="mt-2 text-xs text-aegis-text-muted">
                  Outbound events are cryptographically signed using an HMAC-SHA256 signature header.
                </p>
                <form onSubmit={(e) => void handleCreateWebhook(e)} className="mt-4 space-y-3">
                  <div>
                    <label htmlFor="webhook-url-input" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                      Destination HTTPS URL
                    </label>
                    <input
                      id="webhook-url-input"
                      type="url"
                      required
                      value={webhookUrl}
                      onChange={(e) => setWebhookUrl(e.target.value)}
                      placeholder="https://api.yourdomain.com/webhooks/aegis"
                      className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor="webhook-desc-input" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                      Description
                    </label>
                    <input
                      id="webhook-desc-input"
                      type="text"
                      value={webhookDesc}
                      onChange={(e) => setWebhookDesc(e.target.value)}
                      placeholder="Production Payment Event Listener"
                      className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy}
                    className="w-full rounded bg-aegis-accent py-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
                  >
                    {busy ? "Registering…" : "Add Webhook Endpoint"}
                  </button>
                </form>
              </div>
            )}

            <div className={hasPermission("webhooks:manage") ? "lg:col-span-2" : "lg:col-span-3"}>
              <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
                <div className="border-b border-aegis-border pb-3">
                  <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[LISTENER DIRECTORY]</span>
                  <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Configured Endpoints ({endpoints.length})</h2>
                </div>
                <div className="mt-4 space-y-2.5 text-xs">
                  {endpoints.length === 0 ? (
                    <p className="py-4 text-center font-mono text-aegis-text-muted">No outbound webhook endpoints configured.</p>
                  ) : (
                    endpoints.map((ep) => (
                      <div
                        key={ep.id}
                        className="flex flex-wrap items-center justify-between gap-3 rounded border border-aegis-border bg-aegis-card p-3"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="break-all font-mono text-aegis-accent">{ep.url}</span>
                            <StatusBadge label={ep.status} />
                          </div>
                          <p className="mt-1 text-aegis-text-muted">{ep.description || "Subscribed to all events"}</p>
                        </div>
                        {hasPermission("webhooks:manage") && ep.status !== "REVOKED" && (
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteWebhook(ep)}
                            title="Disable Webhook Endpoint"
                            className="inline-flex items-center gap-1 rounded border border-aegis-rose/40 bg-aegis-rose/10 px-2.5 py-1 font-mono text-[11px] text-aegis-rose hover:bg-aegis-rose/20 transition"
                          >
                            <Trash2 className="h-3 w-3" />
                            <span>Disable</span>
                          </button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Webhook Delivery Logs */}
          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="flex items-center justify-between border-b border-aegis-border px-5 py-3">
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[AUDIT // ATTEMPTS]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Recent Webhook Deliveries ({deliveries.length})</h2>
              </div>
              <span className="font-mono text-xs text-aegis-text-muted">Past 50 delivery attempts</span>
            </div>
            <div className="overflow-x-auto">
              <table className="aegis-table w-full text-left text-xs">
                <caption className="sr-only">Webhook delivery log history</caption>
                <thead>
                  <tr>
                    <th>Delivery ID</th>
                    <th>Event Type</th>
                    <th>Status</th>
                    <th>HTTP Code</th>
                    <th>Attempts</th>
                    <th>Delivered At</th>
                    <th>Error Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {deliveries.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-4 py-5 text-center font-mono text-aegis-text-muted">
                        No webhook deliveries logged yet.
                      </td>
                    </tr>
                  ) : (
                    deliveries.map((del) => (
                      <tr key={del.id}>
                        <td className="font-mono text-aegis-text-muted">{truncateId(del.id, 8)}</td>
                        <td className="font-mono font-medium text-aegis-text-primary">{del.event_type}</td>
                        <td>
                          <StatusBadge label={del.status} />
                        </td>
                        <td className="font-mono">
                          {del.response_status ? (
                            <span
                              className={
                                del.response_status < 400
                                  ? "text-aegis-accent"
                                  : "font-semibold text-aegis-rose"
                              }
                            >
                              {del.response_status}
                            </span>
                          ) : (
                            <span className="text-aegis-text-faint">—</span>
                          )}
                        </td>
                        <td className="font-mono text-aegis-text-muted">{del.attempts}</td>
                        <td className="font-mono text-aegis-text-faint">
                          {del.delivered_at ? formatIsoDateTime(del.delivered_at) : "Pending"}
                        </td>
                        <td className="max-w-[200px] truncate font-mono text-[11px] text-aegis-text-muted">
                          {del.last_error ?? "None"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {/* TAB 4: WORKER OUTBOX & DEAD-LETTER QUEUE (DLQ) */}
      {activeTab === "outbox" && (
        <section className="rounded-xl border border-aegis-border bg-aegis-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border px-5 py-3">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[TRANSACTIONAL OUTBOX // AT-LEAST-ONCE]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Worker Outbox Pipeline</h2>
            </div>
            <div className="flex items-center gap-2 font-mono text-xs">
              <span className="text-aegis-text-muted">Filter:</span>
              <button
                type="button"
                onClick={() => setOutboxFilter("ALL")}
                className={`rounded px-2.5 py-1 text-xs transition ${
                  outboxFilter === "ALL"
                    ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
                    : "text-aegis-text-muted hover:text-aegis-text-primary"
                }`}
              >
                All Events
              </button>
              <button
                type="button"
                onClick={() => setOutboxFilter("DEAD_LETTER")}
                className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs transition ${
                  outboxFilter === "DEAD_LETTER"
                    ? "border border-aegis-rose/40 bg-aegis-rose/15 text-aegis-rose font-semibold"
                    : "text-aegis-text-muted hover:text-aegis-rose"
                }`}
              >
                <span>Dead-Letter Queue (DLQ)</span>
                {deadLetterCount > 0 && (
                  <span className="rounded bg-aegis-rose px-1 text-[10px] font-bold text-[#111513]">
                    {deadLetterCount}
                  </span>
                )}
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="aegis-table w-full text-left text-xs">
              <caption className="sr-only">Worker transactional outbox queue</caption>
              <thead>
                <tr>
                  <th>Outbox ID</th>
                  <th>Event Type</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Last Error</th>
                  <th>Queued At</th>
                  <th className="text-right">Controls</th>
                </tr>
              </thead>
              <tbody>
                {outbox.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center font-mono text-aegis-text-muted">
                      {outboxFilter === "DEAD_LETTER"
                        ? "Nominal state: Zero dead-letter events in the worker outbox."
                        : "Outbox queue is currently empty."}
                    </td>
                  </tr>
                ) : (
                  outbox.map((row) => (
                    <tr key={row.id}>
                      <td className="font-mono text-aegis-text-muted">{truncateId(row.id, 10)}</td>
                      <td className="font-mono font-medium text-aegis-text-primary">{row.event_type}</td>
                      <td>
                        <StatusBadge label={row.status} />
                      </td>
                      <td className="font-mono text-aegis-text-muted">{row.attempts}</td>
                      <td className="max-w-[220px] truncate font-mono text-[11px] text-aegis-rose">
                        {row.last_error ?? "—"}
                      </td>
                      <td className="font-mono text-aegis-text-faint">{formatIsoDateTime(row.created_at)}</td>
                      <td className="text-right">
                        {row.status === "DEAD_LETTER" && hasPermission("worker:manage") && (
                          <button
                            type="button"
                            onClick={() => void handleRequeue(row.id)}
                            className="inline-flex items-center gap-1 rounded border border-aegis-accent/40 bg-aegis-accent/10 px-2.5 py-1 font-mono text-[11px] text-aegis-accent hover:bg-aegis-accent/20 transition"
                          >
                            <RefreshCw className="h-3 w-3" />
                            <span>Requeue</span>
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
      )}

      {/* API Key Rotate / Revoke Dialog */}
      <ConfirmDialog
        open={confirmKeyAction !== null}
        title={confirmKeyAction?.type === "rotate" ? "Rotate API Key Secret" : "Revoke API Key"}
        description={
          confirmKeyAction?.type === "rotate"
            ? `Revoke existing secret for "${confirmKeyAction.key.name}" and issue a fresh plaintext key immediately?`
            : confirmKeyAction
              ? `Permanently revoke "${confirmKeyAction.key.name}" (${confirmKeyAction.key.key_prefix}…)? Active agents using it will fail authorization.`
              : ""
        }
        confirmLabel={confirmKeyAction?.type === "rotate" ? "Rotate Secret" : "Revoke Key"}
        destructive={confirmKeyAction?.type === "revoke"}
        busy={busy}
        onCancel={() => setConfirmKeyAction(null)}
        onConfirm={() => void handleKeyAction()}
      />

      {/* Delete Webhook Dialog */}
      <ConfirmDialog
        open={confirmDeleteWebhook !== null}
        title="Disable Webhook Endpoint"
        description={
          confirmDeleteWebhook
            ? `Are you sure you want to disable outbound event delivery to ${confirmDeleteWebhook.url}?`
            : ""
        }
        confirmLabel="Disable Endpoint"
        destructive={true}
        busy={busy}
        onCancel={() => setConfirmDeleteWebhook(null)}
        onConfirm={() => void handleDeleteWebhook()}
      />
    </AppShell>
  );
}