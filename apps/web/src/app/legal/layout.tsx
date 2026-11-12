import Link from "next/link";
import React from "react";
import { ShieldCheck } from "lucide-react";

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-aegis-bg text-aegis-text-primary flex flex-col justify-between">
      {/* Top Navbar */}
      <header className="sticky top-0 z-20 border-b border-aegis-border bg-aegis-surface/95 px-6 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded border border-aegis-accent/40 bg-aegis-accent/10 text-aegis-accent">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold tracking-wider text-aegis-text-primary">AEGIS</span>
                <span className="rounded bg-aegis-card px-1.5 py-0.2 font-mono text-[10px] text-aegis-accent border border-aegis-border">
                  LEGAL CENTER
                </span>
              </div>
              <span className="font-mono text-[11px] text-aegis-text-muted">Regulatory Compliance & Trust</span>
            </div>
          </Link>

          <nav className="flex items-center gap-4 font-mono text-xs text-aegis-text-muted">
            <Link href="/legal/terms" className="hover:text-aegis-accent transition">
              Terms
            </Link>
            <Link href="/legal/privacy" className="hover:text-aegis-accent transition">
              Privacy
            </Link>
            <Link href="/legal/dpa" className="hover:text-aegis-accent transition">
              DPA
            </Link>
            <Link
              href="/status"
              className="rounded border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-primary hover:bg-aegis-secondary transition"
            >
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
      <footer className="border-t border-aegis-border bg-aegis-surface py-6 text-center font-mono text-xs text-aegis-text-muted">
        <div className="mx-auto max-w-5xl px-6 flex flex-wrap items-center justify-between gap-3">
          <div>© {new Date().getFullYear()} AEGIS Platform Inc. All rights reserved.</div>
          <div className="flex gap-4">
            <Link href="/login" className="hover:text-aegis-accent transition">Operator Login</Link>
            <Link href="/dashboard" className="hover:text-aegis-accent transition">Dashboard</Link>
            <Link href="/status" className="hover:text-aegis-accent transition">Status</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}