"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";
import {
  Activity,
  Bot,
  Code2,
  Compass,
  CreditCard,
  FileSearch,
  History,
  LogOut,
  Menu,
  PlusCircle,
  Scale,
  Settings,
  ShieldCheck,
  Wallet,
  X,
  AlertCircle,
} from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: Activity },
  { href: "/onboarding", label: "Setup Wizard", icon: Compass },
  { href: "/agents", label: "Agents & Merchants", icon: Bot },
  { href: "/passports", label: "Passports & Budgets", icon: Wallet },
  { href: "/payments", label: "Payments & Approvals", icon: CreditCard },
  { href: "/ghostpay", label: "GhostPay Replay", icon: FileSearch },
  { href: "/disputes", label: "DisputeOS", icon: Scale },
  { href: "/audit", label: "Audit Log", icon: History },
  { href: "/developer", label: "Developer Portal", icon: Code2 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  const { session, loading, switchOrganization, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Switcher error toast
  const [switcherError, setSwitcherError] = useState<string | null>(null);

  // Create Org Modal
  const [showCreateOrgModal, setShowCreateOrgModal] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [newOrgSlug, setNewOrgSlug] = useState("");
  const [createOrgBusy, setCreateOrgBusy] = useState(false);
  const [createOrgError, setCreateOrgError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !session) {
      router.replace("/login");
    }
  }, [loading, router, session]);

  if (loading || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-aegis-bg text-slate-300">
        <div className="flex items-center gap-3 rounded-xl border border-aegis-border bg-aegis-surface px-5 py-4 text-sm">
          <ShieldCheck className="h-5 w-5 text-sky-400" />
          <span>Verifying AEGIS session…</span>
        </div>
      </div>
    );
  }

  async function handleSwitch(orgId: string) {
    if (orgId === "__create__") {
      setShowCreateOrgModal(true);
      return;
    }
    setSwitcherError(null);
    try {
      await switchOrganization(orgId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to switch organization";
      setSwitcherError(msg);
      // Auto-clear after 6 seconds
      setTimeout(() => setSwitcherError(null), 6000);
    }
  }

  async function handleCreateOrg(e: React.FormEvent) {
    e.preventDefault();
    setCreateOrgBusy(true);
    setCreateOrgError(null);
    try {
      const created = await apiRequest<{ id: string; name: string; slug: string }>("/v1/orgs", {
        method: "POST",
        body: { name: newOrgName.trim(), slug: newOrgSlug.trim().toLowerCase() },
      });
      setShowCreateOrgModal(false);
      setNewOrgName("");
      setNewOrgSlug("");
      // Switch to newly created organization
      await switchOrganization(created.id);
    } catch (err) {
      setCreateOrgError(err instanceof Error ? err.message : "Failed to create organization");
    } finally {
      setCreateOrgBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-aegis-bg text-slate-100">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-sky-500 focus:px-4 focus:py-2 focus:font-semibold focus:text-slate-950"
      >
        Skip to main content
      </a>

      {/* Switcher Error Toast */}
      {switcherError && (
        <div
          role="alert"
          aria-live="assertive"
          className="fixed bottom-4 right-4 z-50 flex items-center gap-2.5 rounded-xl border border-rose-500/50 bg-rose-950/90 px-4 py-3 text-xs text-rose-200 shadow-xl backdrop-blur"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
          <span>{switcherError}</span>
          <button
            type="button"
            onClick={() => setSwitcherError(null)}
            className="ml-2 text-rose-400 hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="flex min-h-screen">
        {/* Desktop Sidebar */}
        <aside className="hidden w-64 shrink-0 flex-col border-r border-aegis-border bg-aegis-surface lg:flex">
          <div className="flex items-center gap-2.5 border-b border-aegis-border px-5 py-4">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-500/15 text-sky-400 ring-1 ring-sky-400/30">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-bold tracking-wide text-white">AEGIS</div>
              <div className="text-[11px] text-slate-400">Financial Black Box</div>
            </div>
          </div>

          <nav aria-label="Primary navigation" className="flex-1 space-y-1 p-3">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                    active
                      ? "bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30"
                      : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Quick links & user panel */}
          <div className="border-t border-aegis-border p-3 text-[11px] text-slate-400">
            <div className="flex items-center justify-between px-2 py-1">
              <Link href="/status" className="hover:text-sky-300">
                System Status
              </Link>
              <Link href="/legal/terms" className="hover:text-sky-300">
                Legal & DPA
              </Link>
            </div>
          </div>

          <div className="border-t border-aegis-border p-4 text-xs text-slate-400">
            <div className="truncate font-medium text-slate-200">{session.email}</div>
            <div className="mt-1 flex items-center justify-between">
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-sky-300">
                {session.active_role}
              </span>
              <button
                type="button"
                onClick={logout}
                className="inline-flex items-center gap-1 text-slate-300 hover:text-rose-300"
              >
                <LogOut className="h-3.5 w-3.5" />
                Sign out
              </button>
            </div>
          </div>
        </aside>

        {/* Main Column */}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border bg-aegis-bg/90 px-4 py-3 backdrop-blur lg:px-8">
            <div className="flex items-center gap-3">
              <button
                type="button"
                aria-label="Open navigation menu"
                aria-expanded={mobileNavOpen}
                onClick={() => setMobileNavOpen((prev) => !prev)}
                className="rounded-lg border border-aegis-border bg-aegis-surface p-2 text-slate-200 lg:hidden"
              >
                {mobileNavOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
              </button>
              <div>
                <h1 className="text-lg font-semibold text-white">{title}</h1>
                {subtitle && <p className="text-xs text-slate-400">{subtitle}</p>}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <label htmlFor="org-switcher" className="sr-only">
                Active Organization
              </label>
              <select
                id="org-switcher"
                value={session.active_tenant_id}
                onChange={(e) => void handleSwitch(e.target.value)}
                className="rounded-lg border border-aegis-border bg-aegis-surface px-3 py-1.5 text-xs text-slate-100"
              >
                {session.organizations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name} ({org.role})
                  </option>
                ))}
              </select>

              <button
                type="button"
                title="Create New Organization"
                onClick={() => setShowCreateOrgModal(true)}
                className="inline-flex items-center gap-1 rounded-lg border border-aegis-border bg-aegis-surface px-2.5 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800 hover:text-sky-300"
              >
                <PlusCircle className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">New Org</span>
              </button>
            </div>
          </header>

          {mobileNavOpen && (
            <nav
              aria-label="Mobile navigation"
              className="border-b border-aegis-border bg-aegis-surface p-3 lg:hidden"
            >
              <div className="grid grid-cols-2 gap-1.5">
                {NAV_ITEMS.map((item) => {
                  const Icon = item.icon;
                  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setMobileNavOpen(false)}
                      className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${
                        active ? "bg-sky-500/15 text-sky-300" : "text-slate-300 hover:bg-slate-800"
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                      <span>{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </nav>
          )}

          <main id="main-content" className="flex-1 p-4 lg:p-8">
            {children}
          </main>
        </div>
      </div>

      {/* Organization Creation Modal (GAP-022) */}
      {showCreateOrgModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-org-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-aegis-border bg-aegis-panel p-6 text-slate-100 shadow-2xl">
            <div className="flex items-center justify-between border-b border-aegis-border pb-3">
              <h2 id="create-org-modal-title" className="text-base font-semibold text-white">
                Create Organization
              </h2>
              <button
                type="button"
                onClick={() => {
                  setShowCreateOrgModal(false);
                  setCreateOrgError(null);
                }}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {createOrgError && (
              <div
                role="alert"
                aria-live="assertive"
                className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-xs text-rose-200"
              >
                {createOrgError}
              </div>
            )}

            <form onSubmit={(e) => void handleCreateOrg(e)} className="mt-4 space-y-4">
              <div>
                <label htmlFor="modal-org-name" className="block text-xs font-medium text-slate-300">
                  Organization Name <span aria-hidden="true">*</span>
                </label>
                <input
                  id="modal-org-name"
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
                  placeholder="Acme Financial Technologies"
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-surface px-3 py-2 text-xs text-white"
                />
              </div>

              <div>
                <label htmlFor="modal-org-slug" className="block text-xs font-medium text-slate-300">
                  Organization Slug <span aria-hidden="true">*</span>
                </label>
                <input
                  id="modal-org-slug"
                  type="text"
                  required
                  pattern={"^[a-z0-9\\-]+$"}
                  value={newOrgSlug}
                  onChange={(e) => setNewOrgSlug(e.target.value)}
                  placeholder="acme-fintech"
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-surface px-3 py-2 text-xs text-white"
                />
                <span className="mt-1 block text-[11px] text-slate-400">
                  Unique subdomain / identifier for this workspace.
                </span>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={createOrgBusy}
                  onClick={() => {
                    setShowCreateOrgModal(false);
                    setCreateOrgError(null);
                  }}
                  className="rounded-lg border border-aegis-border px-3.5 py-2 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createOrgBusy}
                  className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                >
                  {createOrgBusy ? "Creating…" : "Create & Switch"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
