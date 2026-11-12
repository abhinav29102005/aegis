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
  ExternalLink,
} from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

interface NavGroup {
  label: string;
  items: {
    href: string;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    code?: string;
  }[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "PLATFORM CORE",
    items: [
      { href: "/dashboard", label: "Overview", icon: Activity, code: "00" },
      { href: "/onboarding", label: "Setup Wizard", icon: Compass, code: "WIZ" },
    ],
  },
  {
    label: "GUARDIAN CONTROLS",
    items: [
      { href: "/agents", label: "Agents & Merchants", icon: Bot, code: "AGT" },
      { href: "/passports", label: "Passports & Budgets", icon: Wallet, code: "PAS" },
      { href: "/payments", label: "Payments & Approvals", icon: CreditCard, code: "PAY" },
    ],
  },
  {
    label: "FORENSICS & EVIDENCE",
    items: [
      { href: "/ghostpay", label: "GhostPay Replay", icon: FileSearch, code: "GHO" },
      { href: "/disputes", label: "DisputeOS Workspace", icon: Scale, code: "DSP" },
      { href: "/audit", label: "Chained Audit Log", icon: History, code: "AUD" },
    ],
  },
  {
    label: "CONFIGURATION",
    items: [
      { href: "/developer", label: "Developer Portal", icon: Code2, code: "DEV" },
      { href: "/settings", label: "Settings & Access", icon: Settings, code: "SET" },
    ],
  },
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
      <div className="flex min-h-screen items-center justify-center bg-aegis-bg text-aegis-text-muted">
        <div className="flex items-center gap-3 border border-aegis-border bg-aegis-surface px-5 py-4 font-mono text-xs shadow-editorial">
          <ShieldCheck className="h-4 w-4 text-aegis-accent animate-pulse" />
          <span>AUTHENTICATING OPERATOR SESSION…</span>
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
      await switchOrganization(created.id);
    } catch (err) {
      setCreateOrgError(err instanceof Error ? err.message : "Failed to create organization");
    } finally {
      setCreateOrgBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-aegis-bg text-aegis-text-primary selection:bg-aegis-accent selection:text-aegis-bg">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-aegis-accent focus:bg-aegis-accent focus:px-4 focus:py-2 focus:font-mono focus:text-xs focus:font-semibold focus:text-aegis-bg"
      >
        Skip to main content
      </a>

      {/* Switcher Error Toast */}
      {switcherError && (
        <div
          role="alert"
          aria-live="assertive"
          className="fixed bottom-4 right-4 z-50 flex items-center gap-2.5 border border-[#4A2828] bg-[#211212] px-4 py-3 font-mono text-xs text-[#EF5350] shadow-panel backdrop-blur"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-[#EF5350]" />
          <span>{switcherError}</span>
          <button
            type="button"
            onClick={() => setSwitcherError(null)}
            className="ml-2 text-[#EF5350] hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="flex min-h-screen">
        {/* Desktop Sidebar */}
        <aside className="hidden w-64 shrink-0 flex-col border-r border-aegis-border bg-aegis-surface lg:flex">
          {/* Brand header */}
          <div className="flex items-center gap-3 border-b border-aegis-border px-5 py-4">
            <div className="flex h-8 w-8 items-center justify-center border border-aegis-accent/40 bg-aegis-accent/10 text-aegis-accent">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-sm font-bold tracking-wider text-aegis-text-primary">AEGIS</span>
                <span className="border border-aegis-border-active bg-aegis-card px-1 py-0.2 font-mono text-[9px] text-aegis-text-muted">
                  OS
                </span>
              </div>
              <div className="font-mono text-[10px] text-aegis-text-faint tracking-tight">FINANCIAL CONTROL</div>
            </div>
          </div>

          {/* Navigation Groups */}
          <nav aria-label="Primary navigation" className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
            {NAV_GROUPS.map((group) => (
              <div key={group.label}>
                <div className="px-2.5 pb-1.5 font-mono text-[9px] font-semibold uppercase tracking-widest text-aegis-text-faint">
                  {group.label}
                </div>
                <div className="space-y-0.5">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={`group flex items-center justify-between rounded-[2px] px-2.5 py-1.5 text-xs font-medium transition-colors ${
                          active
                            ? "border-l-2 border-aegis-accent bg-aegis-secondary text-aegis-text-primary pl-2 font-semibold"
                            : "text-aegis-text-muted hover:bg-aegis-card hover:text-aegis-text-primary"
                        }`}
                      >
                        <div className="flex items-center gap-2.5">
                          <Icon
                            className={`h-3.5 w-3.5 shrink-0 transition-colors ${
                              active ? "text-aegis-accent" : "text-aegis-text-muted group-hover:text-aegis-text-primary"
                            }`}
                          />
                          <span>{item.label}</span>
                        </div>
                        {item.code && (
                          <span className="font-mono text-[9px] text-aegis-text-faint group-hover:text-aegis-text-muted">
                            {item.code}
                          </span>
                        )}
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>

          {/* Subsystem & Status Bar */}
          <div className="border-t border-aegis-border px-4 py-2.5 font-mono text-[10px] text-aegis-text-faint flex items-center justify-between">
            <Link href="/status" className="flex items-center gap-1.5 hover:text-aegis-accent transition-colors">
              <span className="h-1.5 w-1.5 rounded-full bg-aegis-accent animate-pulse" />
              <span>CORE ACTIVE</span>
            </Link>
            <Link href="/legal/terms" className="hover:text-aegis-text-primary transition-colors flex items-center gap-1">
              <span>LEGAL</span>
              <ExternalLink className="h-2.5 w-2.5" />
            </Link>
          </div>

          {/* Operator Profile */}
          <div className="border-t border-aegis-border bg-aegis-card/80 p-3.5">
            <div className="truncate font-mono text-xs font-medium text-aegis-text-primary">{session.email}</div>
            <div className="mt-2 flex items-center justify-between">
              <span className="border border-[#3A4A28] bg-[#162112] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-aegis-accent">
                {session.active_role}
              </span>
              <button
                type="button"
                onClick={logout}
                className="inline-flex items-center gap-1 font-mono text-[11px] text-aegis-text-muted hover:text-[#EF5350] transition-colors"
              >
                <LogOut className="h-3 w-3" />
                <span>EXIT</span>
              </button>
            </div>
          </div>
        </aside>

        {/* Main Column */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* Top Bar */}
          <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border bg-aegis-bg/95 px-4 py-3 backdrop-blur-md lg:px-8">
            <div className="flex items-center gap-3">
              <button
                type="button"
                aria-label="Open navigation menu"
                aria-expanded={mobileNavOpen}
                onClick={() => setMobileNavOpen((prev) => !prev)}
                className="border border-aegis-border bg-aegis-surface p-1.5 text-aegis-text-muted hover:text-aegis-text-primary lg:hidden"
              >
                {mobileNavOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
              </button>
              <div>
                <h1 className="text-base font-semibold tracking-tight text-aegis-text-primary sm:text-lg">{title}</h1>
                {subtitle && <p className="font-mono text-xs text-aegis-text-muted">{subtitle}</p>}
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <div className="flex items-center border border-aegis-border bg-aegis-surface px-2 py-1">
                <span className="font-mono text-[10px] uppercase tracking-wider text-aegis-text-faint mr-2 hidden sm:inline">
                  TENANT:
                </span>
                <label htmlFor="org-switcher" className="sr-only">
                  Active Organization
                </label>
                <select
                  id="org-switcher"
                  value={session.active_tenant_id}
                  onChange={(e) => void handleSwitch(e.target.value)}
                  className="bg-transparent font-mono text-xs text-aegis-text-primary focus:outline-none cursor-pointer"
                >
                  {session.organizations.map((org) => (
                    <option key={org.id} value={org.id} className="bg-aegis-surface text-aegis-text-primary">
                      {org.name} [{org.role}]
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="button"
                title="Create New Organization"
                onClick={() => setShowCreateOrgModal(true)}
                className="inline-flex items-center gap-1.5 border border-aegis-border bg-aegis-surface px-2.5 py-1.5 font-mono text-xs text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-accent transition-colors"
              >
                <PlusCircle className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">NEW TENANT</span>
              </button>
            </div>
          </header>

          {/* Mobile Navigation Drawer */}
          {mobileNavOpen && (
            <nav
              aria-label="Mobile navigation"
              className="border-b border-aegis-border bg-aegis-surface p-4 lg:hidden"
            >
              <div className="grid grid-cols-2 gap-2">
                {NAV_GROUPS.flatMap((g) => g.items).map((item) => {
                  const Icon = item.icon;
                  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setMobileNavOpen(false)}
                      className={`flex items-center gap-2 border px-2.5 py-2 text-xs font-mono transition-colors ${
                        active
                          ? "border-aegis-accent bg-aegis-secondary text-aegis-accent font-semibold"
                          : "border-aegis-border bg-aegis-card text-aegis-text-muted hover:text-aegis-text-primary"
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span>{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </nav>
          )}

          {/* Main Content Body */}
          <main id="main-content" className="flex-1 p-4 lg:p-8">
            {children}
          </main>
        </div>
      </div>

      {/* Organization Creation Modal */}
      {showCreateOrgModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-org-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md border border-aegis-border bg-aegis-surface p-6 text-aegis-text-primary shadow-panel rounded-sm">
            <div className="flex items-center justify-between border-b border-aegis-border pb-3">
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                  TENANT PROVISIONING
                </span>
                <h2 id="create-org-modal-title" className="mt-1 text-base font-semibold text-aegis-text-primary">
                  Create Isolated Organization
                </h2>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShowCreateOrgModal(false);
                  setCreateOrgError(null);
                }}
                className="text-aegis-text-muted hover:text-aegis-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {createOrgError && (
              <div
                role="alert"
                aria-live="assertive"
                className="mt-4 border border-[#4A2828] bg-[#211212] px-4 py-3 font-mono text-xs text-[#EF5350]"
              >
                {createOrgError}
              </div>
            )}

            <form onSubmit={(e) => void handleCreateOrg(e)} className="mt-4 space-y-4">
              <div>
                <label htmlFor="modal-org-name" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                  Organization Legal Name <span aria-hidden="true" className="text-aegis-accent">*</span>
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
                  placeholder="Acme Financial Infrastructure"
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="modal-org-slug" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                  Tenant Identifier Slug <span aria-hidden="true" className="text-aegis-accent">*</span>
                </label>
                <input
                  id="modal-org-slug"
                  type="text"
                  required
                  pattern={"^[a-z0-9\\-]+$"}
                  value={newOrgSlug}
                  onChange={(e) => setNewOrgSlug(e.target.value)}
                  placeholder="acme-infra"
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                />
                <span className="mt-1.5 block font-mono text-[10px] text-aegis-text-faint">
                  Immutable namespace for budget isolation & ledger partitioning.
                </span>
              </div>

              <div className="flex justify-end gap-2.5 pt-3 border-t border-aegis-border-subtle">
                <button
                  type="button"
                  disabled={createOrgBusy}
                  onClick={() => {
                    setShowCreateOrgModal(false);
                    setCreateOrgError(null);
                  }}
                  className="border border-aegis-border bg-aegis-card px-4 py-2 font-mono text-xs uppercase tracking-wider text-aegis-text-muted hover:text-aegis-text-primary hover:border-aegis-border-active"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createOrgBusy}
                  className="border border-aegis-accent bg-aegis-accent px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50"
                >
                  {createOrgBusy ? "Provisioning…" : "Provision & Switch"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
