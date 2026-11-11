"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime } from "@/lib/format";

interface MemberRow {
  membership_id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  status: string;
  created_at: string;
}

const ROLES = [
  "OWNER",
  "FINANCE_ADMIN",
  "RISK_ANALYST",
  "DISPUTE_OPERATOR",
  "DEVELOPER",
  "AGENT_RUNTIME",
  "VIEWER",
];

export default function SettingsPage() {
  const { session, hasPermission, switchOrganization } = useAuth();
  const [orgName, setOrgName] = useState("");
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [memberEmail, setMemberEmail] = useState("");
  const [memberFullName, setMemberFullName] = useState("");
  const [memberPassword, setMemberPassword] = useState("");
  const [memberRole, setMemberRole] = useState("RISK_ANALYST");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      setMembers(m);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load organization members");
    }
  }, [session]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

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
      setError(err instanceof Error ? err.message : "Failed to update organization");
    } finally {
      setBusy(false);
    }
  }

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
      setNotice("Organization member added.");
      await loadSettings();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add member");
    } finally {
      setBusy(false);
    }
  }

  async function handleRoleChange(userId: string, role: string) {
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
      setNotice("Member RBAC role updated.");
      await loadSettings();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update role");
    }
  }

  return (
    <AppShell title="Organization & RBAC Settings" subtitle="Manage tenant profile and least-privilege human roles.">
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

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
          <h2 className="text-sm font-semibold text-white">Organization Profile</h2>
          <form onSubmit={handleUpdateOrgName} className="mt-3 space-y-3">
            <div>
              <label htmlFor="org-name" className="block text-xs font-medium text-slate-300">
                Organization Name
              </label>
              <input
                id="org-name"
                type="text"
                required
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                disabled={!hasPermission("org:manage")}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-sm text-white disabled:opacity-60"
              />
            </div>
            <div className="text-xs text-slate-400">
              Tenant ID: <span className="font-mono text-slate-300">{session?.active_tenant_id}</span> · Your Role:{" "}
              <span className="font-semibold text-sky-300">{session?.active_role}</span>
            </div>
            {hasPermission("org:manage") && (
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
              >
                Save Organization Name
              </button>
            )}
          </form>
        </section>

        {hasPermission("members:manage") && (
          <section className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
            <h2 className="text-sm font-semibold text-white">Add Team Member</h2>
            <form onSubmit={handleAddMember} className="mt-3 grid gap-3 sm:grid-cols-2">
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
                aria-label="Initial password (new user)"
                value={memberPassword}
                onChange={(e) => setMemberPassword(e.target.value)}
                placeholder="Initial password (if new user)"
                className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
              />
              <select
                aria-label="Member role"
                value={memberRole}
                onChange={(e) => setMemberRole(e.target.value)}
                className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={busy}
                className="sm:col-span-2 rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400"
              >
                Add Member
              </button>
            </form>
          </section>
        )}
      </div>

      <section className="mt-6 rounded-xl border border-aegis-border bg-aegis-surface">
        <div className="border-b border-aegis-border px-5 py-3">
          <h2 className="text-sm font-semibold text-white">Organization Members ({members.length})</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Organization RBAC members</caption>
            <thead className="border-b border-aegis-border bg-aegis-panel/60 uppercase text-slate-400">
              <tr>
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5">Role</th>
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
                        onChange={(e) => void handleRoleChange(m.user_id, e.target.value)}
                        className="rounded border border-aegis-border bg-aegis-panel px-2 py-1 text-xs text-white"
                      >
                        {ROLES.map((r) => (
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
    </AppShell>
  );
}
