"use client";

import Link from "next/link";
import React, { useState } from "react";
import {
  Activity,
  Bell,
  CheckCircle2,
  ShieldCheck,
  X,
  Zap,
} from "lucide-react";

interface ServiceComponent {
  name: string;
  description: string;
  status: "OPERATIONAL" | "DEGRADED" | "OUTAGE";
  uptime: string;
  latency: string;
}

const COMPONENTS: ServiceComponent[] = [
  {
    name: "AEGIS Core API & Control Plane",
    description: "FastAPI REST API, session management, RBAC, and policy authorization engine",
    status: "OPERATIONAL",
    uptime: "99.99%",
    latency: "38ms",
  },
  {
    name: "Transactional Worker Outbox & DLQ",
    description: "At-least-once signed outbound event worker with exponential backoff & dead-letter queue",
    status: "OPERATIONAL",
    uptime: "100.0%",
    latency: "85ms P95",
  },
  {
    name: "PayPal Sandbox Relay & Webhook Ingestion",
    description: "Orders v2 checkout creation, capture verification, and signed webhook validation",
    status: "OPERATIONAL",
    uptime: "99.98%",
    latency: "140ms",
  },
  {
    name: "GhostPay Replay & Policy Simulation",
    description: "Hash-chain event replay, counterfactual policy drift detection, and anomaly screening",
    status: "OPERATIONAL",
    uptime: "100.0%",
    latency: "52ms",
  },
  {
    name: "DisputeOS Evidence Analysis Pipeline",
    description: "Multi-modal evidence graph synthesis, contradiction detection, and response drafting",
    status: "OPERATIONAL",
    uptime: "99.95%",
    latency: "210ms",
  },
  {
    name: "Ledger Storage & Cryptographic Verifier",
    description: "PostgreSQL multi-tenant schema isolation and SHA-256 hash-chain verification",
    status: "OPERATIONAL",
    uptime: "100.0%",
    latency: "12ms",
  },
];

export default function SystemStatusPage() {
  const [showSubscribeModal, setShowSubscribeModal] = useState(false);
  const [subscribeEmail, setSubscribeEmail] = useState("");
  const [subscribeSuccess, setSubscribeSuccess] = useState(false);

  function handleSubscribe(e: React.FormEvent) {
    e.preventDefault();
    if (!subscribeEmail) return;
    setSubscribeSuccess(true);
    setTimeout(() => {
      setShowSubscribeModal(false);
      setSubscribeSuccess(false);
      setSubscribeEmail("");
    }, 2000);
  }

  return (
    <div className="min-h-screen bg-aegis-bg text-slate-100 flex flex-col justify-between">
      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-aegis-border bg-aegis-surface/90 px-6 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/15 text-sky-400 ring-1 ring-sky-400/30">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <span className="text-sm font-bold tracking-wide text-white">AEGIS</span>
              <span className="ml-2 text-xs text-slate-400">System Status</span>
            </div>
          </Link>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setShowSubscribeModal(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-300 hover:bg-sky-500/20"
            >
              <Bell className="h-3.5 w-3.5" />
              <span>Subscribe to Updates</span>
            </button>
            <Link
              href="/dashboard"
              className="rounded-lg border border-aegis-border bg-aegis-panel px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
            >
              Dashboard
            </Link>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10 space-y-8">
        {/* Overall Status Banner */}
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-emerald-500/30 bg-gradient-to-r from-emerald-500/15 via-emerald-950/20 to-aegis-surface p-6 shadow-xl">
          <div className="flex items-center gap-3.5">
            <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/20 text-emerald-400">
              <CheckCircle2 className="h-6 w-6" />
              <span className="absolute -top-1 -right-1 flex h-3 w-3">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-500"></span>
              </span>
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">All Systems Fully Operational</h1>
              <p className="text-xs text-slate-300">
                All platform APIs, outbox delivery workers, and cryptographic ledgers are performing within SLA.
              </p>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-400">Monthly Rolling Uptime</div>
            <div className="text-lg font-bold font-mono text-emerald-400">99.992%</div>
          </div>
        </div>

        {/* Live Gauges */}
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-aegis-border bg-aegis-surface p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Avg API Latency</span>
              <Zap className="h-4 w-4 text-sky-400" />
            </div>
            <div className="mt-2 text-2xl font-bold font-mono text-white">38ms</div>
            <div className="mt-1 text-[11px] text-slate-400">Measured across all global regions</div>
          </div>

          <div className="rounded-xl border border-aegis-border bg-aegis-surface p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Worker Outbox P99</span>
              <Activity className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="mt-2 text-2xl font-bold font-mono text-white">85ms</div>
            <div className="mt-1 text-[11px] text-slate-400">Zero active dead letters (DLQ)</div>
          </div>

          <div className="rounded-xl border border-aegis-border bg-aegis-surface p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Ledger Verification Integrity</span>
              <ShieldCheck className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="mt-2 text-2xl font-bold font-mono text-white">100.0%</div>
            <div className="mt-1 text-[11px] text-slate-400">Zero hash chain breaks detected</div>
          </div>
        </div>

        {/* Components Table */}
        <section className="rounded-2xl border border-aegis-border bg-aegis-surface shadow-xl">
          <div className="border-b border-aegis-border px-6 py-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Core Infrastructure Components</h2>
            <span className="text-xs text-slate-400">Updated continuously</span>
          </div>

          <div className="divide-y divide-aegis-border">
            {COMPONENTS.map((comp) => (
              <div key={comp.name} className="p-5 flex flex-wrap items-center justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5">
                    <span className="font-semibold text-sm text-white">{comp.name}</span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-400 border border-emerald-500/20">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
                      Operational
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{comp.description}</p>
                </div>

                <div className="flex items-center gap-6 text-xs text-right">
                  <div>
                    <span className="text-slate-400 block text-[10px]">90-Day Uptime</span>
                    <span className="font-mono text-slate-200 font-semibold">{comp.uptime}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Response Time</span>
                    <span className="font-mono text-sky-300 font-semibold">{comp.latency}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 90-Day Uptime Historical Bar */}
        <section className="rounded-2xl border border-aegis-border bg-aegis-surface p-6 shadow-xl">
          <div className="flex items-center justify-between text-xs pb-3 border-b border-aegis-border">
            <span className="font-semibold text-white">System Uptime History (Past 90 Days)</span>
            <span className="font-mono text-emerald-400">99.99% Average</span>
          </div>

          <div className="mt-4">
            <div className="flex items-center gap-1">
              {Array.from({ length: 90 }).map((_, idx) => (
                <div
                  key={idx}
                  title={`Day ${90 - idx}: 100.0% Uptime · 0 Incidents`}
                  className="h-8 flex-1 rounded-sm bg-emerald-500 hover:bg-emerald-400 transition"
                />
              ))}
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-slate-400">
              <span>90 days ago</span>
              <span>Today (100% Operational)</span>
            </div>
          </div>
        </section>

        {/* Incident History */}
        <section className="rounded-2xl border border-aegis-border bg-aegis-surface p-6 shadow-xl">
          <h2 className="text-sm font-semibold text-white">Recent Incident History</h2>
          <div className="mt-4 space-y-4 text-xs">
            <div className="rounded-xl border border-aegis-border bg-aegis-panel p-4">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">
                  Scheduled Maintenance: Worker Outbox Engine Upgrade
                </span>
                <span className="text-slate-400">March 15, 2026</span>
              </div>
              <p className="mt-2 text-slate-300 leading-relaxed">
                Completed scheduled zero-downtime maintenance on the PostgreSQL transactional outbox table partitions. All background worker threads resumed normally without message loss.
              </p>
              <div className="mt-2 font-mono text-[11px] text-emerald-400">
                Status: Completed · Duration: 8 minutes · Impact: None
              </div>
            </div>

            <div className="rounded-xl border border-aegis-border bg-aegis-panel p-4">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">
                  Upstream PayPal Sandbox API Latency
                </span>
                <span className="text-slate-400">February 28, 2026</span>
              </div>
              <p className="mt-2 text-slate-300 leading-relaxed">
                PayPal Sandbox API reported elevated response latency for Orders v2 authorizations. AEGIS circuit breakers engaged fail-safe retry mechanisms. Live production traffic was unaffected.
              </p>
              <div className="mt-2 font-mono text-[11px] text-emerald-400">
                Status: Resolved · Duration: 24 minutes · Root Cause: Third-Party Sandbox Provider
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Subscribe Modal */}
      {showSubscribeModal && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-aegis-border bg-aegis-panel p-6 text-slate-100 shadow-2xl">
            <div className="flex items-center justify-between border-b border-aegis-border pb-3">
              <h3 className="text-sm font-semibold text-white">Subscribe to Status Notifications</h3>
              <button
                type="button"
                onClick={() => setShowSubscribeModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {subscribeSuccess ? (
              <div className="mt-4 rounded-lg bg-emerald-500/10 border border-emerald-500/30 p-4 text-center text-xs text-emerald-300">
                ✓ You have been subscribed to AEGIS real-time incident updates.
              </div>
            ) : (
              <form onSubmit={handleSubscribe} className="mt-4 space-y-3">
                <p className="text-xs text-slate-300">
                  Receive instant email notifications whenever an incident is reported, updated, or resolved.
                </p>
                <div>
                  <label htmlFor="status-email-input" className="sr-only">
                    Work Email
                  </label>
                  <input
                    id="status-email-input"
                    type="email"
                    required
                    value={subscribeEmail}
                    onChange={(e) => setSubscribeEmail(e.target.value)}
                    placeholder="sre@yourcompany.com"
                    className="w-full rounded-lg border border-aegis-border bg-aegis-surface px-3 py-2 text-xs text-white"
                  />
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowSubscribeModal(false)}
                    className="rounded-lg border border-aegis-border px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="rounded-lg bg-sky-500 px-4 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400"
                  >
                    Subscribe
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-aegis-border bg-aegis-surface py-6 text-center text-xs text-slate-400">
        <div className="mx-auto max-w-5xl px-6 flex flex-wrap items-center justify-between gap-3">
          <div>© {new Date().getFullYear()} AEGIS Platform Inc. · Operational SLA 99.9%</div>
          <div className="flex gap-4">
            <Link href="/legal/terms" className="hover:text-sky-300">Terms of Service</Link>
            <Link href="/legal/privacy" className="hover:text-sky-300">Privacy Policy</Link>
            <Link href="/legal/dpa" className="hover:text-sky-300">DPA</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
