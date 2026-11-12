"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect } from "react";
import { ArrowRight, FileSearch, Lock, Scale, ShieldCheck, Terminal, Cpu } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export default function HomePage() {
  const { session, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && session) {
      router.replace("/dashboard");
    }
  }, [loading, router, session]);

  return (
    <div className="min-h-screen bg-aegis-bg text-aegis-text-primary bg-financial-grid bg-financial-radial selection:bg-aegis-accent selection:text-aegis-bg">
      <div className="mx-auto max-w-6xl px-6 py-8 sm:py-12">
        {/* Top Operational Bar */}
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-aegis-border pb-4 text-xs font-mono text-aegis-text-muted">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5 font-semibold text-aegis-accent">
              <span className="h-2 w-2 rounded-full bg-aegis-accent animate-pulse" />
              FINANCIAL CORE ONLINE
            </span>
            <span className="text-aegis-border">•</span>
            <span>SYSTEM: RC1 PRODUCTION HARDENED</span>
            <span className="text-aegis-border">•</span>
            <span>LEDGER: STRICT HASH-CHAINING</span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/status" className="hover:text-aegis-accent transition-colors">
              NETWORK STATUS
            </Link>
            <span className="text-aegis-border">|</span>
            <span className="text-aegis-text-faint">PAYPAL SANDBOX ORDERS v2</span>
          </div>
        </div>

        {/* Header Navigation */}
        <header className="flex items-center justify-between border border-aegis-border bg-aegis-surface/90 px-6 py-4 backdrop-blur-sm rounded-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center border border-aegis-accent/40 bg-aegis-accent/10 text-aegis-accent">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-base font-bold tracking-wider text-aegis-text-primary">AEGIS</span>
                <span className="border border-aegis-border-active bg-aegis-secondary px-1.5 py-0.5 font-mono text-[10px] text-aegis-text-muted uppercase">
                  FINANCIAL OS
                </span>
              </div>
              <p className="font-mono text-[10px] text-aegis-text-muted tracking-tight">
                AGENTIC ENFORCEMENT & GOVERNANCE
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/status"
              className="hidden sm:inline-flex items-center gap-1.5 font-mono text-xs text-aegis-text-muted hover:text-aegis-text-primary transition-colors px-3 py-1.5"
            >
              <Cpu className="h-3.5 w-3.5 text-aegis-accent" />
              <span>DIAGNOSTICS</span>
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 border border-aegis-accent bg-aegis-accent px-4 py-2 font-mono text-xs font-semibold text-aegis-bg hover:bg-aegis-accent-hover transition-colors tracking-wider"
            >
              <span>ACCESS CONSOLE</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </header>

        {/* Hero Section */}
        <main className="mt-16 sm:mt-24">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 border border-aegis-border bg-aegis-surface px-3 py-1 font-mono text-[11px] text-aegis-accent tracking-widest uppercase">
              <Terminal className="h-3.5 w-3.5 text-aegis-copper" />
              <span>DETERMINISTIC SPENDING GOVERNANCE FOR AUTONOMOUS AGENTS</span>
            </div>
            <h1 className="mt-6 text-4xl font-semibold tracking-tight text-aegis-text-primary sm:text-6xl leading-[1.08]">
              The Financial Black Box <br className="hidden sm:inline" />
              <span className="text-aegis-text-muted">for AI Agents.</span>
            </h1>
            <p className="mt-6 text-base sm:text-lg text-aegis-text-muted leading-relaxed font-sans max-w-2xl">
              Deterministic spending passports enforced before funds move. Read-only forensic replay in GhostPay with zero side effects. Multi-rail dispute adjudication with cryptographically verified evidence.
            </p>

            <div className="mt-10 flex flex-wrap items-center gap-4">
              <Link
                href="/login"
                className="inline-flex items-center gap-2.5 border border-aegis-accent bg-aegis-accent px-6 py-3 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover transition-colors shadow-editorial"
              >
                <span>OPEN OPERATOR CONSOLE</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/status"
                className="inline-flex items-center gap-2 border border-aegis-border bg-aegis-surface px-5 py-3 font-mono text-xs uppercase tracking-wider text-aegis-text-muted hover:text-aegis-text-primary hover:border-aegis-border-active transition-colors"
              >
                <span>VERIFY SYSTEM INTEGRITY</span>
              </Link>
            </div>
          </div>

          {/* Ledger Proof Points */}
          <div className="mt-16 grid grid-cols-2 gap-px border border-aegis-border bg-aegis-border sm:grid-cols-4 font-mono">
            <div className="bg-aegis-surface p-5">
              <span className="text-[11px] uppercase tracking-wider text-aegis-text-muted">POLICY LATENCY</span>
              <div className="mt-2 text-2xl font-bold text-aegis-text-primary tabular-nums">&lt; 12ms</div>
              <p className="mt-1 text-[11px] text-aegis-text-faint">Deterministic policy engine</p>
            </div>
            <div className="bg-aegis-surface p-5">
              <span className="text-[11px] uppercase tracking-wider text-aegis-text-muted">LEDGER CHAIN</span>
              <div className="mt-2 text-2xl font-bold text-aegis-accent tabular-nums">HMAC-SHA256</div>
              <p className="mt-1 text-[11px] text-aegis-text-faint">Monotonic append-only log</p>
            </div>
            <div className="bg-aegis-surface p-5">
              <span className="text-[11px] uppercase tracking-wider text-aegis-text-muted">PAYPAL ISOLATION</span>
              <div className="mt-2 text-2xl font-bold text-aegis-copper tabular-nums">ORDERS v2</div>
              <p className="mt-1 text-[11px] text-aegis-text-faint">Hardened sandbox bridge</p>
            </div>
            <div className="bg-aegis-surface p-5">
              <span className="text-[11px] uppercase tracking-wider text-aegis-text-muted">DISPUTEOS</span>
              <div className="mt-2 text-2xl font-bold text-aegis-text-primary tabular-nums">DUAL-SIGN</div>
              <p className="mt-1 text-[11px] text-aegis-text-faint">Human-in-the-loop review</p>
            </div>
          </div>

          {/* Three Subsystems Grid */}
          <div className="mt-14 grid gap-6 md:grid-cols-3">
            <article className="border border-aegis-border bg-aegis-surface p-6 rounded-sm relative">
              <div className="flex items-center justify-between border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                  SUBSYSTEM 01
                </span>
                <Lock className="h-4 w-4 text-aegis-accent" />
              </div>
              <h2 className="mt-4 text-lg font-semibold text-aegis-text-primary tracking-tight">AgentPay Guardian</h2>
              <p className="mt-2 text-xs leading-relaxed text-aegis-text-muted">
                Deterministic policy evaluation, row-level budget reservation locks, quote hash integrity, and strict human escalation thresholds before PayPal checkout initiation.
              </p>
              <div className="mt-6 border-t border-aegis-border-subtle pt-3 font-mono text-[11px] text-aegis-text-faint flex items-center justify-between">
                <span>GATE: PRE-SETTLEMENT</span>
                <span className="text-aegis-accent">ENFORCED</span>
              </div>
            </article>

            <article className="border border-aegis-border bg-aegis-surface p-6 rounded-sm relative">
              <div className="flex items-center justify-between border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper font-semibold">
                  SUBSYSTEM 02
                </span>
                <FileSearch className="h-4 w-4 text-aegis-copper" />
              </div>
              <h2 className="mt-4 text-lg font-semibold text-aegis-text-primary tracking-tight">GhostPay Forensics</h2>
              <p className="mt-2 text-xs leading-relaxed text-aegis-text-muted">
                Zero-side-effect counterfactual policy simulation, agent DNA profiling, authorization drift detection, and tamper-evident event hash-chain verification.
              </p>
              <div className="mt-6 border-t border-aegis-border-subtle pt-3 font-mono text-[11px] text-aegis-text-faint flex items-center justify-between">
                <span>REPLAY: READ-ONLY</span>
                <span className="text-aegis-copper">ISOLATED</span>
              </div>
            </article>

            <article className="border border-aegis-border bg-aegis-surface p-6 rounded-sm relative">
              <div className="flex items-center justify-between border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-text-primary font-semibold">
                  SUBSYSTEM 03
                </span>
                <Scale className="h-4 w-4 text-aegis-text-primary" />
              </div>
              <h2 className="mt-4 text-lg font-semibold text-aegis-text-primary tracking-tight">DisputeOS</h2>
              <p className="mt-2 text-xs leading-relaxed text-aegis-text-muted">
                Tenant-scoped evidence artifact storage, causal provenance graphs, automated contradiction analysis, and mandatory human sign-off before response transmission.
              </p>
              <div className="mt-6 border-t border-aegis-border-subtle pt-3 font-mono text-[11px] text-aegis-text-faint flex items-center justify-between">
                <span>ADJUDICATION: VERIFIED</span>
                <span className="text-aegis-text-primary">HUMAN-IN-LOOP</span>
              </div>
            </article>
          </div>
        </main>

        {/* Footer */}
        <footer className="mt-20 border-t border-aegis-border pt-8 text-xs font-mono text-aegis-text-faint flex flex-wrap items-center justify-between gap-4">
          <div>
            AEGIS PLATFORM // RELEASE CANDIDATE 1 // COMMIT SHA: <span className="text-aegis-text-muted">816d2e2</span>
          </div>
          <div className="flex items-center gap-6">
            <Link href="/legal/terms" className="hover:text-aegis-text-primary transition-colors">
              TERMS
            </Link>
            <Link href="/legal/privacy" className="hover:text-aegis-text-primary transition-colors">
              PRIVACY
            </Link>
            <Link href="/legal/dpa" className="hover:text-aegis-text-primary transition-colors">
              DPA
            </Link>
          </div>
        </footer>
      </div>
    </div>
  );
}
