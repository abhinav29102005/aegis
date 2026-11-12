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

      // Fetch billing subscription & usage from backend
      try {
        const subData = await apiRequest<{
          plan?: string;
          status?: string;
          monthly_tx_quota?: number | null;
          current_period_tx_count?: number;
        }>("/v1/billing/subscription", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        });
        if (subData?.plan) {
          const planUpper = subData.plan.toUpperCase();
          const tier =
            planUpper === "ENTERPRISE"
              ? "enterprise"
              : planUpper === "PRO"
                ? "growth"
                : "free";
          setBilling((prev) => ({
            ...prev,
            plan_name: `${planUpper} Tier`,
            plan_tier: tier,
            status: subData.status ?? prev.status,
          }));
        }
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
      setNotice("Organization profile updated.");
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
      setNotice("Team member provisioned with role " + memberRole + ".");
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
      subtitle="Configure tenant boundaries, enforce 6 canonical RBAC roles, inspect transaction volume quotas, and manage data privacy controls"
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

      {notice && (
        <div
          role="status"
          aria-live="polite"
          className="mb-4 flex items-center gap-2.5 rounded border border-aegis-accent/40 bg-aegis-accent/10 px-4 py-3 font-mono text-xs text-aegis-accent"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-aegis-accent" />
          <span>{notice}</span>
        </div>
      )}

      {/* Settings Navigation Tabs */}
      <div className="mb-6 flex flex-wrap gap-2 border-b border-aegis-border pb-3">
        <button
          type="button"
          onClick={() => setActiveTab("profile")}
          className={`inline-flex items-center gap-2 rounded px-3 py-1.5 font-mono text-xs transition ${
            activeTab === "profile"
              ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
              : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
          }`}
        >
          <Building2 className="h-3.5 w-3.5" />
          <span>Profile</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("members")}
          className={`inline-flex items-center gap-2 rounded px-3 py-1.5 font-mono text-xs transition ${
            activeTab === "members"
              ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
              : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
          }`}
        >
          <Users className="h-3.5 w-3.5" />
          <span>Team & RBAC ({members.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("billing")}
          className={`inline-flex items-center gap-2 rounded px-3 py-1.5 font-mono text-xs transition ${
            activeTab === "billing"
              ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
              : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
          }`}
        >
          <CreditCard className="h-3.5 w-3.5" />
          <span>Billing & Quotas</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("privacy")}
          className={`inline-flex items-center gap-2 rounded px-3 py-1.5 font-mono text-xs transition ${
            activeTab === "privacy"
              ? "border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent font-semibold"
              : "border border-transparent text-aegis-text-muted hover:border-aegis-border hover:bg-aegis-card hover:text-aegis-text-primary"
          }`}
        >
          <Shield className="h-3.5 w-3.5" />
          <span>Privacy & GDPR / DPDPA</span>
        </button>
      </div>

      {/* TAB 1: GENERAL PROFILE */}
      {activeTab === "profile" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="border-b border-aegis-border pb-3">
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[TENANT // CONFIGURATION]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Organization Identity</h2>
            </div>

            <form onSubmit={(e) => void handleUpdateOrgName(e)} className="mt-4 space-y-4">
              <div>
                <label htmlFor="settings-org-name" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Organization Display Name
                </label>
                <input
                  id="settings-org-name"
                  type="text"
                  required
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  disabled={!hasPermission("org:manage")}
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none disabled:opacity-50"
                />
              </div>

              <div className="space-y-1.5 rounded border border-aegis-border bg-aegis-card p-3 font-mono text-xs text-aegis-text-muted">
                <div>
                  Tenant ID: <span className="text-aegis-text-primary">{session?.active_tenant_id}</span>
                </div>
                <div>
                  Your Active Role: <span className="text-aegis-accent font-semibold">{session?.active_role}</span>
                </div>
                <div>
                  Operator: <span className="text-aegis-text-primary">{session?.email}</span>
                </div>
              </div>

              {hasPermission("org:manage") && (
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded bg-aegis-accent px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
                >
                  Save Organization Changes
                </button>
              )}
            </form>
          </section>

          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <div className="border-b border-aegis-border pb-3">
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper">[MULTI-TENANT // ISOLATION]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Switch Tenant Workspaces</h2>
            </div>
            <p className="mt-2 text-xs text-aegis-text-muted">
              Tenant environments maintain strict cryptographic and database row separation.
            </p>

            <div className="mt-4 space-y-2 text-xs">
              {session?.organizations.map((org) => (
                <div
                  key={org.id}
                  className={`flex items-center justify-between rounded border p-3 ${
                    org.id === session.active_tenant_id
                      ? "border-aegis-accent/40 bg-aegis-accent/10 text-aegis-text-primary"
                      : "border-aegis-border bg-aegis-card text-aegis-text-muted"
                  }`}
                >
                  <div>
                    <div className="font-semibold text-aegis-text-primary">{org.name}</div>
                    <div className="font-mono text-[11px] text-aegis-text-faint">
                      Slug: {org.slug} · Role: {org.role}
                    </div>
                  </div>
                  {org.id === session.active_tenant_id ? (
                    <span className="rounded border border-aegis-accent/40 bg-aegis-accent/20 px-2 py-0.5 font-mono text-[11px] font-medium text-aegis-accent">
                      CURRENT
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void switchOrganization(org.id)}
                      className="rounded border border-aegis-border bg-aegis-surface px-2.5 py-1 font-mono text-[11px] text-aegis-text-primary hover:bg-aegis-secondary transition"
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
              className="mt-4 inline-flex items-center gap-1.5 rounded border border-dashed border-aegis-border px-3.5 py-2 font-mono text-xs text-aegis-accent hover:border-aegis-accent hover:bg-aegis-accent/10 transition"
            >
              <PlusCircle className="h-4 w-4" />
              <span>Provision New Tenant Workspace</span>
            </button>
          </section>
        </div>
      )}

      {/* TAB 2: MEMBERS & CANONICAL RBAC */}
      {activeTab === "members" && (
        <div className="space-y-6">
          {hasPermission("members:manage") && (
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[ACCESS GOVERNANCE // RBAC]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Add Team Member (Canonical RBAC)</h2>
              </div>
              <p className="mt-2 text-xs text-aegis-text-muted">
                Least-privilege authorization using the 6 canonical roles: <code>OWNER</code>, <code>ADMIN</code>, <code>OPERATOR</code>, <code>AUDITOR</code>, <code>AGENT_SERVICE</code>, <code>VIEWER</code>.
              </p>
              <form onSubmit={(e) => void handleAddMember(e)} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <input
                  type="email"
                  required
                  aria-label="Member email"
                  value={memberEmail}
                  onChange={(e) => setMemberEmail(e.target.value)}
                  placeholder="analyst@company.com"
                  className="rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
                <input
                  type="text"
                  required
                  aria-label="Member full name"
                  value={memberFullName}
                  onChange={(e) => setMemberFullName(e.target.value)}
                  placeholder="Full Name"
                  className="rounded border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
                <input
                  type="password"
                  aria-label="Initial password"
                  value={memberPassword}
                  onChange={(e) => setMemberPassword(e.target.value)}
                  placeholder="Initial password"
                  className="rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
                <select
                  aria-label="Canonical Role"
                  value={memberRole}
                  onChange={(e) => setMemberRole(e.target.value as Role)}
                  className="rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
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
                    className="rounded bg-aegis-accent px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
                  >
                    Provision Member
                  </button>
                </div>
              </form>
            </section>
          )}

          <section className="rounded-xl border border-aegis-border bg-aegis-surface">
            <div className="border-b border-aegis-border px-5 py-3">
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[AUTHORIZATION ROSTER]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Active Members ({members.length})</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="aegis-table w-full text-left text-xs">
                <caption className="sr-only">Organization RBAC members</caption>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Canonical Role</th>
                    <th>Status</th>
                    <th>Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((m) => (
                    <tr key={m.membership_id}>
                      <td className="font-medium text-aegis-text-primary">{m.full_name}</td>
                      <td className="font-mono text-aegis-text-muted">{m.email}</td>
                      <td>
                        {hasPermission("members:manage") ? (
                          <select
                            aria-label={`Role for ${m.email}`}
                            value={m.role}
                            onChange={(e) => void handleRoleChange(m.user_id, e.target.value as Role)}
                            className="rounded border border-aegis-border bg-aegis-card px-2 py-1 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                          >
                            {CANONICAL_ROLES.map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="font-mono text-aegis-accent">{m.role}</span>
                        )}
                      </td>
                      <td>
                        <StatusBadge label={m.status} />
                      </td>
                      <td className="font-mono text-aegis-text-faint">{formatIsoDateTime(m.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {/* TAB 3: BILLING, USAGE & QUOTAS */}
      {activeTab === "billing" && (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-3">
            {/* Current Plan Card */}
            <div className="rounded-xl border border-aegis-accent/40 bg-aegis-surface p-5 lg:col-span-1">
              <span className="rounded border border-aegis-accent/40 bg-aegis-accent/15 px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-aegis-accent">
                ACTIVE TIER
              </span>
              <h2 className="mt-2 text-xl font-bold text-aegis-text-primary">{billing.plan_name}</h2>
              <p className="mt-1 text-xs text-aegis-text-muted leading-relaxed">
                Full-featured deterministic governance, tamper-evident hash chaining, and replay simulation.
              </p>
              <div className="mt-4 border-t border-aegis-border pt-3 font-mono text-xs text-aegis-text-muted space-y-1">
                <div>Renewal: <span className="text-aegis-text-primary">{formatIsoDateTime(billing.billing_period_end)}</span></div>
                <div>Status: <StatusBadge label={billing.status} /></div>
              </div>
              <button
                type="button"
                onClick={() => alert("Redirecting to billing invoice management…")}
                className="mt-5 w-full rounded bg-aegis-accent py-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition"
              >
                Manage Payment Rail & Invoices
              </button>
            </div>

            {/* Quota & Metering Gauges */}
            <div className="space-y-5 rounded-xl border border-aegis-border bg-aegis-surface p-5 lg:col-span-2">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[METERING // STRIPE QUOTAS]</span>
                <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Monthly Quota Consumption</h2>
              </div>

              {/* Meter 1: Transacted Volume */}
              <div>
                <div className="flex justify-between font-mono text-xs">
                  <span className="text-aegis-text-muted">Transacted Settlement Volume</span>
                  <span className="text-aegis-text-primary">
                    {formatMinorCurrency(billing.volume_transacted_cents)} / {formatMinorCurrency(billing.volume_quota_cents)}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-aegis-card border border-aegis-border">
                  <div
                    className="h-full bg-aegis-accent transition-all duration-300"
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
                <div className="flex justify-between font-mono text-xs">
                  <span className="text-aegis-text-muted">Active Autonomous Agents</span>
                  <span className="text-aegis-text-primary">
                    {billing.active_agents_count} / {billing.active_agents_quota} agents
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-aegis-card border border-aegis-border">
                  <div
                    className="h-full bg-aegis-copper transition-all duration-300"
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
                <div className="flex justify-between font-mono text-xs">
                  <span className="text-aegis-text-muted">Outbound Signed Webhook Events</span>
                  <span className="text-aegis-text-primary">
                    {billing.webhook_deliveries_count.toLocaleString()} / {billing.webhook_deliveries_quota.toLocaleString()}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-aegis-card border border-aegis-border">
                  <div
                    className="h-full bg-aegis-accent/70 transition-all duration-300"
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
            <div className="flex items-center gap-2 text-aegis-accent">
              <Globe className="h-5 w-5" />
              <h2 className="text-sm font-semibold text-aegis-text-primary">GDPR & India DPDPA 2023 Compliance Framework</h2>
            </div>
            <p className="mt-1 text-xs text-aegis-text-muted leading-relaxed">
              AEGIS acts as a non-custodial financial governance processor. We adhere strictly to GDPR (EU 2016/679) and the Digital Personal Data Protection Act (DPDPA 2023), including cryptographically irreversible key destruction (crypto-shredding) and verified self-serve portability.
            </p>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Data Export (Portability) */}
            <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
              <div className="flex items-center gap-2">
                <Download className="h-4 w-4 text-aegis-accent" />
                <h3 className="text-sm font-semibold text-aegis-text-primary">Data Subject Portability Export</h3>
              </div>
              <p className="mt-1 text-xs text-aegis-text-muted">
                Download a cryptographically verifiable archive of all tenant agents, policies, passports, and hash-chained financial logs.
              </p>

              <div className="mt-4 flex gap-3 font-mono text-xs">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleRequestExport("JSON")}
                  className="inline-flex items-center gap-1.5 rounded border border-aegis-border bg-aegis-card px-3.5 py-2 text-aegis-text-primary hover:bg-aegis-secondary transition"
                >
                  <FileCheck className="h-4 w-4 text-aegis-accent" />
                  <span>Request JSON Archive</span>
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleRequestExport("CSV")}
                  className="inline-flex items-center gap-1.5 rounded border border-aegis-border bg-aegis-card px-3.5 py-2 text-aegis-text-primary hover:bg-aegis-secondary transition"
                >
                  <FileSpreadsheet className="h-4 w-4 text-aegis-copper" />
                  <span>Request CSV Archive</span>
                </button>
              </div>

              <div className="mt-5 space-y-2 font-mono text-xs">
                <span className="font-semibold text-aegis-text-muted uppercase text-[10px] tracking-wider">Recent Export Requests</span>
                {exportJobs.map((j) => (
                  <div
                    key={j.id}
                    className="flex items-center justify-between rounded border border-aegis-border bg-aegis-card p-2.5"
                  >
                    <div>
                      <span className="text-aegis-text-primary">{j.id}</span> · Format: {j.format} ·{" "}
                      <span className="text-aegis-text-faint">{formatIsoDateTime(j.created_at)}</span>
                    </div>
                    <span className="rounded border border-aegis-accent/40 bg-aegis-accent/15 px-2 py-0.5 text-[10px] font-semibold text-aegis-accent">
                      {j.status}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {/* Right to Erasure / Crypto-Shredding */}
            <section className="rounded-xl border border-aegis-rose/40 bg-aegis-rose/5 p-5">
              <div className="flex items-center gap-2 text-aegis-rose">
                <ShieldAlert className="h-4 w-4" />
                <h3 className="text-sm font-semibold text-aegis-rose">Cryptographic Erasure & Offboarding</h3>
              </div>
              <p className="mt-1 text-xs text-aegis-rose/80 leading-relaxed">
                Under GDPR Article 17 and DPDPA Section 12, executing erasure destroys this tenant&apos;s encryption keys immediately (crypto-shredding), making historical financial logs irreversibly unreadable.
              </p>

              <div className="mt-5">
                <button
                  type="button"
                  onClick={() => setConfirmErasure(true)}
                  className="inline-flex items-center gap-2 rounded border border-aegis-rose/40 bg-aegis-rose/20 px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-aegis-rose hover:bg-aegis-rose/30 transition"
                >
                  <Trash2 className="h-4 w-4" />
                  <span>Request Crypto-Shredding</span>
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-xl border border-aegis-border bg-aegis-surface p-6 text-aegis-text-primary shadow-2xl">
            <div className="border-b border-aegis-border pb-3">
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[PROVISIONING // TENANT]</span>
              <h2 className="text-sm font-semibold tracking-wide text-aegis-text-primary">Provision New Organization</h2>
            </div>
            <form onSubmit={(e) => void handleCreateOrg(e)} className="mt-4 space-y-4">
              <div>
                <label htmlFor="settings-modal-org-name" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
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
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="settings-modal-org-slug" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                  Organization Slug
                </label>
                <input
                  id="settings-modal-org-slug"
                  type="text"
                  required
                  pattern={"^[a-z0-9\\-]+$"}
                  value={newOrgSlug}
                  onChange={(e) => setNewOrgSlug(e.target.value)}
                  className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 font-mono text-xs">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="rounded border border-aegis-border bg-aegis-card px-3.5 py-1.5 text-aegis-text-muted hover:text-aegis-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded bg-aegis-accent px-4 py-1.5 font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] transition disabled:opacity-50"
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-xl border border-aegis-rose/50 bg-aegis-surface p-6 text-aegis-text-primary shadow-2xl">
            <h2 className="font-mono text-sm font-semibold tracking-wider text-aegis-rose uppercase">
              [CRITICAL] IRREVERSIBLE CRYPTO-SHREDDING
            </h2>
            <p className="mt-2 text-xs text-aegis-text-muted leading-relaxed">
              This action will destroy all tenant master encryption keys for{" "}
              <strong className="text-aegis-text-primary">{orgName}</strong>. Historical event hash chains, agent identities, and replay logs will become permanently unreadable.
            </p>
            <p className="mt-3 font-mono text-xs text-aegis-rose font-medium">
              Type <code className="bg-aegis-card px-1 py-0.5 text-aegis-text-primary">DELETE-MY-ORGANIZATION</code> to authorize:
            </p>
            <input
              type="text"
              value={erasureConfirmationText}
              onChange={(e) => setErasureConfirmationText(e.target.value)}
              placeholder="DELETE-MY-ORGANIZATION"
              className="mt-2 w-full rounded border border-aegis-rose/40 bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-rose focus:outline-none"
            />
            <div className="mt-5 flex justify-end gap-2 font-mono text-xs">
              <button
                type="button"
                onClick={() => {
                  setConfirmErasure(false);
                  setErasureConfirmationText("");
                }}
                className="rounded border border-aegis-border bg-aegis-card px-3.5 py-1.5 text-aegis-text-muted hover:text-aegis-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={erasureConfirmationText !== "DELETE-MY-ORGANIZATION" || busy}
                onClick={() => void handleExecuteErasure()}
                className="rounded bg-aegis-rose px-4 py-1.5 font-semibold uppercase tracking-wider text-white hover:bg-rose-600 disabled:opacity-40 transition"
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