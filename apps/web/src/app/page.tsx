"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect } from "react";
import { ArrowRight, FileSearch, Lock, Scale, ShieldCheck } from "lucide-react";
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
    <div className="min-h-screen bg-aegis-bg text-slate-100">
      <div className="mx-auto max-w-5xl px-6 py-16">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-400 ring-1 ring-sky-400/30">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div>
              <span className="text-lg font-bold tracking-wide text-white">AEGIS</span>
              <span className="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">Platform</span>
            </div>
          </div>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400"
          >
            Open Console
            <ArrowRight className="h-4 w-4" />
          </Link>
        </header>

        <main className="mt-16">
          <p className="text-xs font-semibold uppercase tracking-widest text-sky-400">
            Agentic Enforcement, Governance and Investigation System
          </p>
          <h1 className="mt-3 text-4xl font-bold tracking-tight text-white sm:text-5xl">
            The Financial Black Box for AI Agents.
          </h1>
          <p className="mt-5 max-w-2xl text-base text-slate-300">
            Enforce deterministic spending passports before money moves, replay historical transactions safely in
            GhostPay without side effects, and resolve payment disputes with evidence-grounded human review.
          </p>

          <div className="mt-8 flex flex-wrap gap-4">
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-sky-400"
            >
              Sign In or Create Organization
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          <div className="mt-14 grid gap-6 md:grid-cols-3">
            <article className="rounded-xl border border-aegis-border bg-aegis-surface p-6">
              <Lock className="h-6 w-6 text-sky-400" />
              <h2 className="mt-4 text-base font-semibold text-white">AgentPay Guardian</h2>
              <p className="mt-2 text-sm text-slate-400">
                Deterministic policy engine, row-locked budget reservations, quote integrity hashes, and human approval
                gates over PayPal Sandbox checkout.
              </p>
            </article>
            <article className="rounded-xl border border-aegis-border bg-aegis-surface p-6">
              <FileSearch className="h-6 w-6 text-emerald-400" />
              <h2 className="mt-4 text-base font-semibold text-white">GhostPay Forensics</h2>
              <p className="mt-2 text-sm text-slate-400">
                Read-only policy replay, counterfactual what-if simulation, authorization drift detection, and hash-chain
                audit verification.
              </p>
            </article>
            <article className="rounded-xl border border-aegis-border bg-aegis-surface p-6">
              <Scale className="h-6 w-6 text-amber-400" />
              <h2 className="mt-4 text-base font-semibold text-white">DisputeOS</h2>
              <p className="mt-2 text-sm text-slate-400">
                Tenant-isolated evidence artifact storage, provenance graphs, contradiction detection, and strict human
                sign-off before any submission.
              </p>
            </article>
          </div>
        </main>
      </div>
    </div>
  );
}
