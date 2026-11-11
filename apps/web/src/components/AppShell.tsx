"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";
import {
  Activity,
  Bot,
  Code2,
  CreditCard,
  FileSearch,
  History,
  LogOut,
  Menu,
  Scale,
  Settings,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: Activity },
  { href: "/agents", label: "Agents & Merchants", icon: Bot },
  { href: "/passports", label: "Passports & Budgets", icon: Wallet },
  { href: "/payments", label: "Payments & Approvals", icon: CreditCard },
  { href: "/ghostpay", label: "GhostPay Replay", icon: FileSearch },
  { href: "/disputes", label: "DisputeOS", icon: Scale },
  { href: "/audit", label: "Audit Log", icon: History },
  { href: "/developer", label: "Developer Portal", icon: Code2 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  const { session, loading, switchOrganization, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

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

  return (
    <div className="min-h-screen bg-aegis-bg text-slate-100">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-sky-500 focus:px-4 focus:py-2 focus:font-semibold focus:text-slate-950"
      >
        Skip to main content
      </a>

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

          <div className="border-t border-aegis-border p-4 text-xs text-slate-400">
            <div className="truncate font-medium text-slate-200">{session.email}</div>
            <div className="mt-1 flex items-center justify-between">
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-sky-300">{session.active_role}</span>
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

            <div className="flex items-center gap-3">
              <label htmlFor="org-switcher" className="sr-only">
                Active Organization
              </label>
              <select
                id="org-switcher"
                value={session.active_tenant_id}
                onChange={(e) => void switchOrganization(e.target.value)}
                className="rounded-lg border border-aegis-border bg-aegis-surface px-3 py-1.5 text-sm text-slate-100"
              >
                {session.organizations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name} ({org.role})
                  </option>
                ))}
              </select>
            </div>
          </header>

          {mobileNavOpen && (
            <nav aria-label="Mobile navigation" className="border-b border-aegis-border bg-aegis-surface p-3 lg:hidden">
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
    </div>
  );
}
