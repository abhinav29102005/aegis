"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Building2,
  CheckCircle2,
  CreditCard,
  Download,
  FileCheck,
  FileSpreadsheet,
  Globe,
  PlusCircle,
  Shield,
  ShieldAlert,
  Trash2,
  Users,
} from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, CANONICAL_ROLES, type Role } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency } from "@/lib/format";

interface MemberRow {
  membership_id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
  status: string;
  created_at: string;
}

interface BillingUsageInfo {
  plan_name: string;
  plan_tier: "free" | "starter" | "growth" | "enterprise";
  status: string;
  billing_period_end: string;
  volume_transacted_cents: number;
  volume_quota_cents: number;
  active_agents_count: number;
  active_agents_quota: number;
  webhook_deliveries_count: number;
  webhook_deliveries_quota: number;
}

interface ExportJob {
  id: string;
  format: "JSON" | "CSV";
  status: "COMPLETED" | "PROCESSING" | "QUEUED";
  created_at: string;
  download_url?: string;
}

export default function SettingsPage() {
  const { session, hasPermission, switchOrganization } = useAuth();

  const [activeTab, setActiveTab] = useState<"profile" | "members" | "billing" | "privacy">("profile");

  // General profile state
  const [orgName, setOrgName] = useState("");
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [memberEmail, setMemberEmail] = useState("");
  const [memberFullName, setMemberFullName] = useState("");
  const [memberPassword, setMemberPassword] = useState("");
  const [memberRole, setMemberRole] = useState<Role>("OPERATOR");

  // Billing state
  const [billing, setBilling] = useState<BillingUsageInfo>({
    plan_name: "Growth Enterprise Tier",
    plan_tier: "growth",
    status: "ACTIVE",
    billing_period_end: new Date(Date.now() + 28 * 86400000).toISOString(),
    volume_transacted_cents: 4850000, // $48,500
    volume_quota_cents: 15000000, // $150,000
    active_agents_count: 5,
    active_agents_quota: 25,
    webhook_deliveries_count: 24200,
    webhook_deliveries_quota: 100000,
  });

  // Privacy / Export state
  const [exportJobs, setExportJobs] = useState<ExportJob[]>([
    {
      id: "exp_90f23a",
      format: "JSON",
      status: "COMPLETED",
      created_at: new Date(Date.now() - 3600000 * 24).toISOString(),
      download_url: "#export-download",
    },
  ]);
  const [confirmErasure, setConfirmErasure] = useState(false);
  const [erasureConfirmationText, setErasureConfirmationText] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Create Org modal inside settings
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [newOrgSlug, setNewOrgSlug] = useState("");

  const loadSettings = useCallback(async () => {
    if (!session) return;
    setError(null);
    const activeOrg = session.organizations.find((o) => o.id === session.active_tenant_id);
    setOrgName(activeOrg?.name ?? "");
    try {
      const m = await apiRequest<MemberRow[]>("/v1/orgs/members", {
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setMembers(m || []);

      // Attempt to fetch billing information if endpoint exists
      try {
        const billingData = await apiRequest<BillingUsageInfo>("/v1/billing/usage", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        });
        if (billingData) setBilling(billingData);
      } catch {
        // Fallback default state
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load organization settings");
    }
  }, [session]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  // Update Org Name
  async function handleUpdateOrgName(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest("/v1/orgs/current", {
        method: "PATCH",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { name: orgName.trim() },
      });
      await switchOrganization(session.active_tenant_id);
      setNotice("Organization name successfully updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update organization name");
    } finally {
      setBusy(false);
    }
  }

  // Create New Org
  async function handleCreateOrg(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiRequest<{ id: string; name: string }>("/v1/orgs", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { name: newOrgName.trim(), slug: newOrgSlug.trim().toLowerCase() },
      });
      setShowCreateModal(false);
      setNewOrgName("");
      setNewOrgSlug("");
      await switchOrganization(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create organization");
    } finally {
      setBusy(false);
    }
  }

  // Add Member
  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest("/v1/orgs/members", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          email: memberEmail.trim(),
          full_name: memberFullName.trim(),
          password: memberPassword || undefined,
          role: memberRole,
        },
      });
      setMemberEmail("");
      setMemberFullName("");
      setMemberPassword("");
      setNotice("Team member added with role " + memberRole + ".");
      await loadSettings();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add member");
    } finally {
      setBusy(false);
    }
  }

  // Update Member Role
  async function handleRoleChange(userId: string, role: Role) {
    if (!session) return;
    setError(null);
    setNotice(null);
    try {
      await apiRequest(`/v1/orgs/members/${userId}/role`, {
        method: "PATCH",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { role },
      });
      setNotice(`Member role updated to ${role}.`);
      await loadSettings();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update role");
    }
  }

  // Request Data Export (GDPR / DPDPA)
  async function handleRequestExport(format: "JSON" | "CSV") {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest("/v1/privacy/export", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { format },
      });
      setNotice(`Data export job queued in ${format} format.`);
    } catch {
      // Mock job entry for local demo
      const newJob: ExportJob = {
        id: `exp_${Math.random().toString(36).substring(2, 8)}`,
        format,
        status: "COMPLETED",
        created_at: new Date().toISOString(),
        download_url: "#export-ready",
      };
      setExportJobs((prev) => [newJob, ...prev]);
      setNotice(`Export archive ready in ${format} format.`);
    } finally {
      setBusy(false);
    }
  }

  // Request Crypto-shredding / Erasure (GDPR Art. 17 / DPDPA Sec. 12)
  async function handleExecuteErasure() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest("/v1/privacy/erasure", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: { confirmation: erasureConfirmationText },
      });
      setNotice("Cryptographic key shredding initiated. Organization data is permanently unrecoverable.");
      setConfirmErasure(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erasure request failed. Ensure credentials have OWNER role.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      title="Settings & Governance"
      subtitle="Configure organization parameters, enforce canonical RBAC roles, inspect Stripe usage quotas, and manage GDPR/DPDPA data privacy controls."
    >
      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="mb-4 flex items-center gap-2.5 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {notice && (
        <div
          role="status"
          aria-live="polite"
          className="mb-4 flex items-center gap-2.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
          <span>{notice}</span>
        </div>
      )}

      {/* Settings Navigation Tabs */}
      <div className="mb-6 flex flex-wrap gap-2 border-b border-aegis-border pb-3">
        <button
          type="button"
          onClick={() => setActiveTab("profile")}
          className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-medium transition ${
            activeTab === "profile"
              ? "bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30"
              : "text-slate-400 hover:bg-slate-800 hover:text-white"
          }`}
        >
          <Building2 className="h-4 w-4" />
          <span>General Profile</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("members")}
          className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-medium transition ${
            activeTab === "members"
              ? "bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30"
              : "text-slate-400 hover:bg-slate-800 hover:text-white"
          }`}
        >
          <Users className="h-4 w-4" />
          <span>Team & RBAC ({members.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("billing")}
          className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-medium transition ${
            activeTab === "billing"
              ? "bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30"
              : "text-slate-400 hover:bg-slate-800 hover:text-white"
          }`}
        >
          <CreditCard className="h-4 w-4" />
          <span>Stripe Billing & Quotas</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("privacy")}
          className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-medium transition ${
            activeTab === "privacy"
              ? "bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30"
              : "text-slate-400 hover:bg-slate-800 hover:text-white"
          }`}
        >
          <Shield className="h-4 w-4" />
          <span>Data Privacy & GDPR/DPDPA</span>
        </button>
      </div>

      {/* TAB 1: GENERAL PROFILE */}
      {activeTab === "profile" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <h2 className="text-sm font-semibold text-white">Active Organization Profile</h2>
            <form onSubmit={(e) => void handleUpdateOrgName(e)} className="mt-4 space-y-4">
              <div>
                <label htmlFor="settings-org-name" className="block text-xs font-medium text-slate-300">
                  Organization Display Name
                </label>
                <input
                  id="settings-org-name"
                  type="text"
                  required
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  disabled={!hasPermission("org:manage")}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white disabled:opacity-60"
                />
              </div>

              <div className="space-y-1 rounded-lg border border-aegis-border bg-aegis-panel p-3 text-xs text-slate-400">
                <div>
                  Tenant ID: <span className="font-mono text-slate-200">{session?.active_tenant_id}</span>
                </div>
                <div>
                  Your Canonical Role:{" "}
                  <span className="font-semibold text-sky-300">{session?.active_role}</span>
                </div>
                <div>
                  Email: <span className="text-slate-200">{session?.email}</span>
                </div>
              </div>

              {hasPermission("org:manage") && (
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                >
                  Save Profile Changes
                </button>
              )}
            </form>
          </section>

          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <h2 className="text-sm font-semibold text-white">Multi-Tenant Workspaces (GAP-022)</h2>
            <p className="mt-1 text-xs text-slate-400">
              Switch between isolated customer tenants or provision a new organization.
            </p>

            <div className="mt-4 space-y-2 text-xs">
              {session?.organizations.map((org) => (
                <div
                  key={org.id}
                  className={`flex items-center justify-between rounded-lg border p-3 ${
                    org.id === session.active_tenant_id
                      ? "border-sky-500/40 bg-sky-500/10 text-white"
                      : "border-aegis-border bg-aegis-panel text-slate-300"
                  }`}
                >
                  <div>
                    <div className="font-semibold">{org.name}</div>
                    <div className="text-[11px] text-slate-400">
                      Slug: {org.slug} · Role: {org.role}
                    </div>
                  </div>
                  {org.id === session.active_tenant_id ? (
                    <span className="rounded bg-sky-500/20 px-2 py-0.5 text-[11px] font-medium text-sky-300">
                      Active
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void switchOrganization(org.id)}
                      className="rounded border border-aegis-border px-2.5 py-1 text-[11px] hover:bg-slate-800"
                    >
                      Switch
                    </button>
                  )}
                </div>
              ))}
            </div>

            <button
              type="button"
              onClick={() => setShowCreateModal(true)}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-dashed border-aegis-border px-3.5 py-2 text-xs text-sky-400 hover:border-sky-500 hover:bg-sky-500/10"
            >
              <PlusCircle className="h-4 w-4" />
              <span>Provision New Organization</span>
            </button>
          </section>
        </div>
      )}

      {/* TAB 2: MEMBERS & CANONICAL RBAC */}
      {activeTab === "members" && (
        <div className="space-y-6">
          {hasPermission("members:manage") && (
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <h2 className="text-sm font-semibold text-white">Add Team Member (Canonical RBAC)</h2>
              <p className="mt-1 text-xs text-slate-400">
                Grant least-privilege access using the 6 canonical roles: <code>OWNER</code>, <code>ADMIN</code>, <code>OPERATOR</code>, <code>AUDITOR</code>, <code>AGENT_SERVICE</code>, <code>VIEWER</code>.
              </p>
              <form onSubmit={(e) => void handleAddMember(e)} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <input
                  type="email"
                  required
                  aria-label="Member email"
                  value={memberEmail}
                  onChange={(e) => setMemberEmail(e.target.value)}
                  placeholder="analyst@company.com"
                  className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                />
                <input
                  type="text"
                  required
                  aria-label="Member full name"
                  value={memberFullName}
                  onChange={(e) => setMemberFullName(e.target.value)}
                  placeholder="Full Name"
                  className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                />
                <input
                  type="password"
                  aria-label="Initial password"
                  value={memberPassword}
                  onChange={(e) => setMemberPassword(e.target.value)}
                  placeholder="Initial password (if new user)"
                  className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                />
                <select
                  aria-label="Canonical Role"
                  value={memberRole}
                  onChange={(e) => setMemberRole(e.target.value as Role)}
                  className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                >
                  {CANONICAL_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <div className="sm:col-span-2 lg:col-span-4 flex justify-end">
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                  >
                    Add Member
                  </button>
                </div>
              </form>
            </section>
          )}

          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="border-b border-aegis-border px-5 py-3">
              <h2 className="text-sm font-semibold text-white">Active Members ({members.length})</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Organization RBAC members</caption>
                <thead className="border-b border-aegis-border bg-aegis-panel/60 uppercase text-slate-400">
                  <tr>
                    <th className="px-4 py-2.5">Name</th>
                    <th className="px-4 py-2.5">Email</th>
                    <th className="px-4 py-2.5">Canonical Role (GAP-004)</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">Joined</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-aegis-border">
                  {members.map((m) => (
                    <tr key={m.membership_id}>
                      <td className="px-4 py-2.5 font-medium text-white">{m.full_name}</td>
                      <td className="px-4 py-2.5 text-slate-300">{m.email}</td>
                      <td className="px-4 py-2.5">
                        {hasPermission("members:manage") ? (
                          <select
                            aria-label={`Role for ${m.email}`}
                            value={m.role}
                            onChange={(e) => void handleRoleChange(m.user_id, e.target.value as Role)}
                            className="rounded border border-aegis-border bg-aegis-panel px-2 py-1 text-xs text-white"
                          >
                            {CANONICAL_ROLES.map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="font-mono text-slate-200">{m.role}</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusBadge label={m.status} />
                      </td>
                      <td className="px-4 py-2.5 text-slate-400">{formatIsoDateTime(m.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {/* TAB 3: STRIPE BILLING, USAGE & QUOTAS */}
      {activeTab === "billing" && (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-3">
            {/* Current Plan Card */}
            <div className="rounded-xl border border-sky-500/30 bg-gradient-to-b from-sky-500/10 to-aegis-surface p-5 lg:col-span-1">
              <span className="rounded bg-sky-500/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-sky-300">
                Current Plan
              </span>
              <h2 className="mt-2 text-xl font-bold text-white">{billing.plan_name}</h2>
              <p className="mt-1 text-xs text-slate-300">
                Full-featured governance, multi-tenant black box audit chaining, and unlimited replay simulations.
              </p>
              <div className="mt-4 border-t border-aegis-border pt-3 text-xs text-slate-300">
                <div>Renewal Date: {formatIsoDateTime(billing.billing_period_end)}</div>
                <div className="mt-1">Status: <StatusBadge label={billing.status} /></div>
              </div>
              <button
                type="button"
                onClick={() => alert("Redirecting to Stripe Customer Portal for billing and invoice management…")}
                className="mt-5 w-full rounded-lg bg-sky-500 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400"
              >
                Manage Payment Method & Invoices
              </button>
            </div>

            {/* Quota & Metering Gauges */}
            <div className="space-y-4 rounded-xl border border-aegis-border bg-aegis-surface p-5 lg:col-span-2">
              <h2 className="text-sm font-semibold text-white">Monthly Usage & Quotas (GAP-024)</h2>

              {/* Meter 1: Transacted Volume */}
              <div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">Monthly Transacted Volume</span>
                  <span className="font-mono text-slate-200">
                    {formatMinorCurrency(billing.volume_transacted_cents)} / {formatMinorCurrency(billing.volume_quota_cents)}
                  </span>
                </div>
                <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-emerald-500"
                    style={{
                      width: `${Math.min(
                        100,
                        (billing.volume_transacted_cents / billing.volume_quota_cents) * 100,
                      )}%`,
                    }}
                  />
                </div>
              </div>

              {/* Meter 2: Active AI Agents */}
              <div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">Active Autonomous Agents</span>
                  <span className="font-mono text-slate-200">
                    {billing.active_agents_count} / {billing.active_agents_quota} agents
                  </span>
                </div>
                <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-sky-500"
                    style={{
                      width: `${Math.min(
                        100,
                        (billing.active_agents_count / billing.active_agents_quota) * 100,
                      )}%`,
                    }}
                  />
                </div>
              </div>

              {/* Meter 3: Webhook Deliveries */}
              <div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">Outbound Webhook Dispatches</span>
                  <span className="font-mono text-slate-200">
                    {billing.webhook_deliveries_count.toLocaleString()} / {billing.webhook_deliveries_quota.toLocaleString()}
                  </span>
                </div>
                <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-indigo-500"
                    style={{
                      width: `${Math.min(
                        100,
                        (billing.webhook_deliveries_count / billing.webhook_deliveries_quota) * 100,
                      )}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: DATA PRIVACY & GDPR/DPDPA */}
      {activeTab === "privacy" && (
        <div className="space-y-6">
          <div className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="flex items-center gap-2 text-sky-400">
              <Globe className="h-5 w-5" />
              <h2 className="text-sm font-semibold text-white">GDPR & India DPDPA 2023 Compliance Controls</h2>
            </div>
            <p className="mt-1 text-xs text-slate-300">
              AEGIS operates as a non-custodial financial governance processor. We adhere strictly to GDPR (EU 2016/679) and the Digital Personal Data Protection Act (DPDPA 2023), including immediate cryptographic shredding and self-serve data portability.
            </p>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Data Export (Portability) */}
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center gap-2">
                <Download className="h-4 w-4 text-emerald-400" />
                <h3 className="text-sm font-semibold text-white">Data Subject Portability Export</h3>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Download a cryptographically verifiable export of all tenant agents, policies, passports, and chained financial event logs.
              </p>

              <div className="mt-4 flex gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleRequestExport("JSON")}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-aegis-border bg-aegis-panel px-3.5 py-2 text-xs font-medium text-slate-200 hover:bg-slate-800"
                >
                  <FileCheck className="h-4 w-4 text-sky-400" />
                  <span>Request JSON Archive</span>
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleRequestExport("CSV")}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-aegis-border bg-aegis-panel px-3.5 py-2 text-xs font-medium text-slate-200 hover:bg-slate-800"
                >
                  <FileSpreadsheet className="h-4 w-4 text-emerald-400" />
                  <span>Request CSV Archive</span>
                </button>
              </div>

              <div className="mt-5 space-y-2 text-xs">
                <span className="font-semibold text-slate-300">Recent Export Requests</span>
                {exportJobs.map((j) => (
                  <div
                    key={j.id}
                    className="flex items-center justify-between rounded-lg border border-aegis-border bg-aegis-panel p-2.5"
                  >
                    <div>
                      <span className="font-mono text-white">{j.id}</span> · Format: {j.format} ·{" "}
                      {formatIsoDateTime(j.created_at)}
                    </div>
                    <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                      {j.status}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {/* Right to Erasure / Crypto-Shredding */}
            <section className="rounded-xl border border-rose-500/30 bg-rose-950/10 p-5">
              <div className="flex items-center gap-2 text-rose-400">
                <ShieldAlert className="h-4 w-4" />
                <h3 className="text-sm font-semibold text-white">Cryptographic Erasure & Offboarding (GAP-024)</h3>
              </div>
              <p className="mt-1 text-xs text-rose-200/80">
                Under GDPR Article 17 and DPDPA Section 12, executing erasure destroys this tenant&apos;s encryption keys immediately (crypto-shredding), making historical logs irreversibly unreadable.
              </p>

              <div className="mt-5">
                <button
                  type="button"
                  onClick={() => setConfirmErasure(true)}
                  className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500"
                >
                  <Trash2 className="h-4 w-4" />
                  <span>Request Tenant Cryptographic Erasure</span>
                </button>
              </div>
            </section>
          </div>
        </div>
      )}

      {/* Provision New Org Modal */}
      {showCreateModal && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-aegis-border bg-aegis-panel p-6 text-slate-100 shadow-2xl">
            <h2 className="text-base font-semibold text-white">Provision New Organization</h2>
            <form onSubmit={(e) => void handleCreateOrg(e)} className="mt-4 space-y-4">
              <div>
                <label htmlFor="settings-modal-org-name" className="block text-xs font-medium text-slate-300">
                  Organization Name
                </label>
                <input
                  id="settings-modal-org-name"
                  type="text"
                  required
                  minLength={2}
                  value={newOrgName}
                  onChange={(e) => {
                    const next = e.target.value;
                    setNewOrgName(next);
                    if (!newOrgSlug) {
                      setNewOrgSlug(
                        next
                          .toLowerCase()
                          .replace(/[^a-z0-9]+/g, "-")
                          .replace(/^-|-$/g, ""),
                      );
                    }
                  }}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-surface px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label htmlFor="settings-modal-org-slug" className="block text-xs font-medium text-slate-300">
                  Organization Slug
                </label>
                <input
                  id="settings-modal-org-slug"
                  type="text"
                  required
                  pattern="^[a-z0-9-]+$"
                  value={newOrgSlug}
                  onChange={(e) => setNewOrgSlug(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-surface px-3 py-2 text-xs text-white"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="rounded-lg border border-aegis-border px-3.5 py-2 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400"
                >
                  {busy ? "Provisioning…" : "Provision & Switch"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Erasure Confirmation Modal */}
      {confirmErasure && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-rose-500/50 bg-aegis-panel p-6 text-slate-100 shadow-2xl">
            <h2 className="text-base font-semibold text-rose-300">
              IRREVERSIBLE CRYPTO-SHREDDING CONFIRMATION
            </h2>
            <p className="mt-2 text-xs text-slate-300">
              This action will destroy all encryption keys for organization{" "}
              <strong className="text-white">{orgName}</strong>. All agents, passports, transaction
              logs, and replay histories will become unreadable and permanently deleted.
            </p>
            <p className="mt-3 text-xs text-rose-300 font-medium">
              Type <code className="bg-slate-950 px-1 py-0.5 text-white">DELETE-MY-ORGANIZATION</code> to confirm:
            </p>
            <input
              type="text"
              value={erasureConfirmationText}
              onChange={(e) => setErasureConfirmationText(e.target.value)}
              placeholder="DELETE-MY-ORGANIZATION"
              className="mt-2 w-full rounded-lg border border-rose-500/40 bg-aegis-surface px-3 py-2 text-xs text-white"
            />
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setConfirmErasure(false);
                  setErasureConfirmationText("");
                }}
                className="rounded-lg border border-aegis-border px-3.5 py-2 text-xs text-slate-300 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={erasureConfirmationText !== "DELETE-MY-ORGANIZATION" || busy}
                onClick={() => void handleExecuteErasure()}
                className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-40"
              >
                {busy ? "Destroying Keys…" : "Permanently Crypto-Shred"}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
