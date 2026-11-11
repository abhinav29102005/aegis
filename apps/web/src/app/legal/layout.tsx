import Link from "next/link";
import React from "react";
import { ShieldCheck } from "lucide-react";

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-aegis-bg text-slate-100 flex flex-col justify-between">
      {/* Top Navbar */}
      <header className="sticky top-0 z-20 border-b border-aegis-border bg-aegis-surface/90 px-6 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/15 text-sky-400 ring-1 ring-sky-400/30">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <span className="text-sm font-bold tracking-wide text-white">AEGIS</span>
              <span className="ml-2 text-xs text-slate-400">Legal & Trust Center</span>
            </div>
          </Link>

          <nav className="flex items-center gap-4 text-xs font-medium text-slate-300">
            <Link href="/legal/terms" className="hover:text-sky-300 hover:underline">
              Terms of Service
            </Link>
            <Link href="/legal/privacy" className="hover:text-sky-300 hover:underline">
              Privacy Policy
            </Link>
            <Link href="/legal/dpa" className="hover:text-sky-300 hover:underline">
              Data Processing Addendum
            </Link>
            <Link href="/status" className="rounded-md border border-aegis-border bg-aegis-panel px-2.5 py-1 text-slate-200 hover:bg-slate-800">
              System Status
            </Link>
          </nav>
        </div>
      </header>

      {/* Main Legal Content */}
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-aegis-border bg-aegis-surface py-6 text-center text-xs text-slate-400">
        <div className="mx-auto max-w-5xl px-6 flex flex-wrap items-center justify-between gap-3">
          <div>© {new Date().getFullYear()} AEGIS Platform Inc. All rights reserved.</div>
          <div className="flex gap-4">
            <Link href="/login" className="hover:text-sky-300">Control Plane Login</Link>
            <Link href="/dashboard" className="hover:text-sky-300">Dashboard</Link>
            <Link href="/status" className="hover:text-sky-300">Status</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
