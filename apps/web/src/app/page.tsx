"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Database,
  ExternalLink,
  Eye,
  FileSearch,
  Fingerprint,
  Lock,
  Play,
  RotateCcw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Zap,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

interface ScenarioStep {
  time: string;
  source: string;
  action: string;
  status: "success" | "blocked" | "info" | "warning";
  detail: string;
}

interface Scenario {
  id: string;
  name: string;
  badge: string;
  agent: string;
  budget: string;
  requestAmount: string;
  merchant: string;
  verdict: "APPROVED" | "INTERCEPTED & BLOCKED" | "ATOMICALLY LOCKED";
  verdictClass: string;
  elapsedMs: number;
  merkleHash: string;
  description: string;
  steps: ScenarioStep[];
}

const SCENARIOS: Scenario[] = [
  {
    id: "compute-provisioning",
    name: "Autonomous Cloud Compute",
    badge: "STANDARD WORKFLOW",
    agent: "devops-provisioner-07",
    budget: "$500.00 / day",
    requestAmount: "$124.50",
    merchant: "api.azure.microsoft.com",
    verdict: "APPROVED",
    verdictClass: "border-aegis-accent bg-aegis-accent/10 text-aegis-accent",
    elapsedMs: 8.4,
    merkleHash: "8f4a19b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abc",
    description: "Autonomous LLM DevOps agent provisions 4x NVIDIA L4 instances within pre-authorized budget bounds.",
    steps: [
      { time: "0.0ms", source: "AGENT[devops-07]", action: "SUBMIT_INTENT", status: "info", detail: "Request $124.50 at Azure Compute API" },
      { time: "1.2ms", source: "GUARDIAN_CORE", action: "PASSPORT_VERIFY", status: "success", detail: "Passport PASS-AZ-99 active, tenant isolation confirmed" },
      { time: "3.8ms", source: "POLICY_ENGINE", action: "EVALUATE_RULES", status: "success", detail: "Daily spend $124.50 <= $500.00 ceiling, merchant whitelisted" },
      { time: "5.1ms", source: "DB_ROUTER", action: "ROW_LEVEL_LOCK", status: "success", detail: "Reserved $124.50 against organization ledger balance" },
      { time: "7.2ms", source: "PAYPAL_CLIENT", action: "ORDERS_V2_AUTHORIZE", status: "success", detail: "Order PP-ORD-88219 created with deterministic quote hash" },
      { time: "8.4ms", source: "MERKLE_ENGINE", action: "CHAIN_AUDIT_BLOCK", status: "success", detail: "Block #14022 appended with HMAC-SHA256 signature" },
    ],
  },
  {
    id: "prompt-injection-escape",
    name: "Prompt Injection Rogue Escape",
    badge: "CRITICAL THREAT BLOCKED",
    agent: "support-copilot-02",
    budget: "$50.00 / day",
    requestAmount: "$2,400.00",
    merchant: "unverified-crypto-broker.io",
    verdict: "INTERCEPTED & BLOCKED",
    verdictClass: "border-[#EF5350] bg-[#EF5350]/10 text-[#EF5350]",
    elapsedMs: 3.6,
    merkleHash: "3b9f4a1290abcdef123456789abcdef0123456789abcdef0123456789abcdef0",
    description: "Attacker tricks customer service agent via jailbreak into transferring funds to an unapproved recipient.",
    steps: [
      { time: "0.0ms", source: "AGENT[support-02]", action: "MALICIOUS_INTENT", status: "warning", detail: "Injected jailbreak triggers $2,400.00 wire transfer" },
      { time: "0.8ms", source: "GUARDIAN_CORE", action: "PASSPORT_VERIFY", status: "info", detail: "Passport PASS-CS-02 policy ceiling is $50.00" },
      { time: "2.1ms", source: "POLICY_ENGINE", action: "RULE_VIOLATION", status: "blocked", detail: "EXCEEDS_MAX_AMOUNT ($2,400 > $50) & MERCHANT_DISALLOWED" },
      { time: "2.8ms", source: "CIRCUIT_BREAKER", action: "HARD_TRIP", status: "blocked", detail: "Execution aborted. Zero outbound payment API calls." },
      { time: "3.6ms", source: "GHOSTPAY_FORENSICS", action: "SECURITY_EVENT", status: "blocked", detail: "High-priority anomaly recorded: Injection incident flagged" },
    ],
  },
  {
    id: "swarm-concurrency",
    name: "Swarm Concurrency Race",
    badge: "CONCURRENCY INVARIANT",
    agent: "procurement-swarm[1..50]",
    budget: "$1,000.00 Shared",
    requestAmount: "50x $30.00 ($1,500 total)",
    merchant: "api.fastly.com",
    verdict: "ATOMICALLY LOCKED",
    verdictClass: "border-aegis-copper bg-aegis-copper/10 text-aegis-copper",
    elapsedMs: 11.2,
    merkleHash: "c0ffeebabe123456789abcdef0123456789abcdef0123456789abcdef01234567",
    description: "50 parallel agents simultaneously purchase assets to exhaust shared budget. AEGIS serializes reservations atomically.",
    steps: [
      { time: "0.0ms", source: "SWARM_AGENTS", action: "CONCURRENT_DISPATCH", status: "info", detail: "50 parallel purchasing threads dispatched simultaneously" },
      { time: "4.1ms", source: "DB_ROUTER", action: "FOR_UPDATE_LOCK", status: "success", detail: "Database row-level semaphore acquired on tenant balance" },
      { time: "7.5ms", source: "GUARDIAN_CORE", action: "SERIALIZED_CHECK", status: "success", detail: "First 33 requests approved ($990.00 total reserved)" },
      { time: "9.8ms", source: "POLICY_ENGINE", action: "BUDGET_EXHAUSTED", status: "blocked", detail: "Request 34..50 rejected: Exceeds remaining $10.00 balance" },
      { time: "11.2ms", source: "LEDGER_AUDIT", action: "BALANCE_INVARIANT", status: "success", detail: "Zero over-allocation: Ledger invariant strictly maintained" },
    ],
  },
];

export default function HomePage() {
  const { session, loading } = useAuth();
  const router = useRouter();
  const [activeScenarioId, setActiveScenarioId] = useState<string>("compute-provisioning");
  const [activeTab, setActiveTab] = useState<"simulator" | "architecture" | "cli">("simulator");

  useEffect(() => {
    if (!loading && session) {
      router.replace("/dashboard");
    }
  }, [loading, router, session]);

  const activeScenario = SCENARIOS.find((s) => s.id === activeScenarioId) ?? SCENARIOS[0];

  return (
    <div className="min-h-screen bg-aegis-bg text-aegis-text-primary bg-financial-grid bg-financial-radial selection:bg-aegis-accent selection:text-aegis-bg">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        
        {/* Global Operational Bar */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-3.5 text-xs font-mono text-aegis-text-muted">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="inline-flex items-center gap-1.5 font-bold text-aegis-accent">
              <span className="h-2 w-2 rounded-full bg-aegis-accent animate-pulse" />
              FINANCIAL CORE ONLINE
            </span>
            <span className="text-aegis-border">•</span>
            <span>SYSTEM: RC-1 HARDENED</span>
            <span className="text-aegis-border">•</span>
            <span>HASH CHAIN: HMAC-SHA256 STRICT</span>
            <span className="text-aegis-border">•</span>
            <span className="text-aegis-accent">453/453 TESTS PASS</span>
          </div>
          <div className="flex items-center gap-4 text-[11px]">
            <Link href="/status" className="hover:text-aegis-accent transition-colors flex items-center gap-1">
              <Cpu className="h-3 w-3 text-aegis-accent" />
              <span>STAGING DIAGNOSTICS</span>
            </Link>
            <span className="text-aegis-border">|</span>
            <span className="text-aegis-text-faint">PAYPAL SANDBOX ORDERS v2</span>
          </div>
        </div>

        {/* Top Navigation */}
        <header className="flex items-center justify-between border border-aegis-border bg-aegis-surface/90 px-6 py-4 backdrop-blur-md rounded-sm shadow-panel">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center border border-aegis-accent/50 bg-aegis-accent/10 text-aegis-accent shadow-[0_0_12px_rgba(0,229,255,0.15)]">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-lg font-bold tracking-wider text-aegis-text-primary">AEGIS</span>
                <span className="border border-aegis-accent/40 bg-aegis-accent/10 px-2 py-0.5 font-mono text-[9px] font-bold text-aegis-accent uppercase tracking-widest">
                  FINANCIAL OS
                </span>
              </div>
              <p className="font-mono text-[10px] text-aegis-text-muted tracking-tight">
                AGENTIC ENFORCEMENT, GOVERNANCE & INVESTIGATION SYSTEM
              </p>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-6 font-mono text-xs text-aegis-text-muted">
            <a href="#simulator" className="hover:text-aegis-text-primary transition-colors">
              LIVE SIMULATOR
            </a>
            <a href="#subsystems" className="hover:text-aegis-text-primary transition-colors">
              SUBSYSTEMS
            </a>
            <a href="#architecture" className="hover:text-aegis-text-primary transition-colors">
              ARCHITECTURE
            </a>
            <a href="#cli" className="hover:text-aegis-text-primary transition-colors">
              SDK & CLI
            </a>
          </nav>

          <div className="flex items-center gap-3">
            <Link
              href="/status"
              className="hidden sm:inline-flex items-center gap-1.5 border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-muted hover:text-aegis-text-primary hover:border-aegis-border-active transition-colors"
            >
              <Cpu className="h-3.5 w-3.5 text-aegis-accent" />
              <span>STATUS</span>
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 border border-aegis-accent bg-aegis-accent px-4 py-2 font-mono text-xs font-bold text-aegis-bg hover:bg-aegis-accent-hover transition-colors tracking-wider shadow-editorial"
            >
              <span>ACCESS CONSOLE</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </header>

        {/* Hero Section */}
        <section className="mt-12 sm:mt-18">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
            
            {/* Left Column: Mission & Statement */}
            <div className="lg:col-span-7">
              <div className="inline-flex items-center gap-2 border border-aegis-accent/30 bg-aegis-accent/5 px-3.5 py-1.5 font-mono text-[11px] text-aegis-accent tracking-widest uppercase">
                <Terminal className="h-3.5 w-3.5 text-aegis-accent" />
                <span>THE FINANCIAL BLACK BOX FOR AUTONOMOUS AI AGENTS</span>
              </div>

              <h1 className="mt-6 text-4xl font-bold tracking-tight text-aegis-text-primary sm:text-6xl leading-[1.08]">
                Deterministic spend control <br className="hidden sm:inline" />
                <span className="text-aegis-text-muted">before funds move.</span>
              </h1>

              <p className="mt-6 text-base sm:text-lg text-aegis-text-muted leading-relaxed font-sans max-w-2xl">
                When AI agents autonomously browse, book, and buy, traditional fraud filters are blind. AEGIS guarantees deterministic spending passports enforced at the kernel layer, zero-side-effect forensic replay in GhostPay, and cryptographically verified dispute adjudication in DisputeOS.
              </p>

              {/* Action Buttons */}
              <div className="mt-8 flex flex-wrap items-center gap-4">
                <Link
                  href="/login"
                  className="inline-flex items-center gap-2.5 border border-aegis-accent bg-aegis-accent px-6 py-3 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover transition-colors shadow-editorial"
                >
                  <span>LAUNCH OPERATOR CONSOLE</span>
                  <ArrowRight className="h-4 w-4" />
                </Link>

                <a
                  href="#simulator"
                  className="inline-flex items-center gap-2 border border-aegis-border bg-aegis-surface px-5 py-3 font-mono text-xs uppercase tracking-wider text-aegis-text-primary hover:border-aegis-accent hover:text-aegis-accent transition-colors"
                >
                  <Play className="h-3.5 w-3.5 text-aegis-accent" />
                  <span>INTERACTIVE BLACK BOX PREVIEW</span>
                </a>
              </div>

              {/* Evaluator Fast Track Callout */}
              <div className="mt-8 border border-aegis-accent/30 bg-aegis-accent/5 p-4 rounded-sm font-mono text-xs max-w-xl">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-aegis-accent font-bold text-[11px] uppercase tracking-wider">
                    <ShieldCheck className="h-4 w-4" />
                    <span>HACKATHON EVALUATOR / JUDGE QUICK ACCESS</span>
                  </div>
                  <span className="text-[10px] text-aegis-text-faint">TENANT: BF1AB00D</span>
                </div>
                <p className="mt-1.5 text-xs text-aegis-text-muted leading-relaxed">
                  Pre-configured Chief Auditor account with pre-seeded autonomous agents, live passports, and 100+ cryptographic audit blocks.
                </p>
                <div className="mt-3 flex items-center gap-3">
                  <Link
                    href="/login"
                    className="inline-flex items-center gap-1.5 border border-aegis-accent bg-aegis-accent/20 px-3 py-1.5 font-mono text-[11px] font-bold text-aegis-accent hover:bg-aegis-accent hover:text-aegis-bg transition-colors uppercase tracking-wider"
                  >
                    <span>1-Click Sign In on Login Screen</span>
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                  <span className="text-[11px] text-aegis-text-faint">Pass: SuperSecurePassword123!@#</span>
                </div>
              </div>
            </div>

            {/* Right Column: Live Terminal Simulator Preview */}
            <div className="lg:col-span-5" id="simulator">
              <div className="border border-aegis-border bg-aegis-surface shadow-panel rounded-sm overflow-hidden">
                
                {/* Terminal Header */}
                <div className="flex items-center justify-between border-b border-aegis-border bg-aegis-card px-4 py-3 font-mono text-xs">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full bg-[#EF5350]/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-aegis-copper/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-aegis-accent/80" />
                    <span className="ml-2 font-bold text-aegis-text-primary tracking-wider">AEGIS KERNEL INTERCEPTOR</span>
                  </div>
                  <span className="text-[10px] text-aegis-accent uppercase font-bold tracking-widest">
                    &lt; 12ms ENFORCED
                  </span>
                </div>

                {/* Scenario Selector Tabs */}
                <div className="grid grid-cols-3 border-b border-aegis-border bg-aegis-bg font-mono text-[11px]">
                  {SCENARIOS.map((sc) => (
                    <button
                      key={sc.id}
                      type="button"
                      onClick={() => setActiveScenarioId(sc.id)}
                      className={`px-3 py-2 text-center transition-colors truncate border-r last:border-r-0 border-aegis-border ${
                        activeScenarioId === sc.id
                          ? "bg-aegis-surface text-aegis-accent font-bold border-b-2 border-b-aegis-accent"
                          : "text-aegis-text-muted hover:text-aegis-text-primary hover:bg-aegis-card/50"
                      }`}
                    >
                      {sc.name}
                    </button>
                  ))}
                </div>

                {/* Active Scenario Details */}
                <div className="p-4 bg-aegis-surface space-y-3 font-mono text-xs">
                  <div className="flex items-center justify-between border-b border-aegis-border/60 pb-2">
                    <div>
                      <span className="text-[10px] uppercase text-aegis-text-faint tracking-wider">ACTIVE AGENT</span>
                      <div className="font-bold text-aegis-text-primary">{activeScenario.agent}</div>
                    </div>
                    <div className="text-right">
                      <span className="text-[10px] uppercase text-aegis-text-faint tracking-wider">AMOUNT REQUESTED</span>
                      <div className="font-bold text-aegis-accent">{activeScenario.requestAmount}</div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-aegis-text-muted">Target Merchant:</span>
                    <span className="text-aegis-text-primary font-semibold">{activeScenario.merchant}</span>
                  </div>

                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-aegis-text-muted">Passport Policy Ceiling:</span>
                    <span className="text-aegis-copper font-semibold">{activeScenario.budget}</span>
                  </div>

                  {/* Verdict Badge */}
                  <div className="pt-1">
                    <div className={`border p-2 text-center font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 ${activeScenario.verdictClass}`}>
                      {activeScenario.verdict === "APPROVED" && <CheckCircle2 className="h-4 w-4" />}
                      {activeScenario.verdict === "INTERCEPTED & BLOCKED" && <ShieldAlert className="h-4 w-4" />}
                      {activeScenario.verdict === "ATOMICALLY LOCKED" && <Lock className="h-4 w-4" />}
                      <span>{activeScenario.verdict} IN {activeScenario.elapsedMs}ms</span>
                    </div>
                  </div>

                  {/* Step Execution Trace */}
                  <div className="mt-3 space-y-1.5 pt-2 border-t border-aegis-border/60 text-[10px]">
                    <div className="text-aegis-text-faint uppercase tracking-wider mb-1 font-semibold">
                      DETERMINISTIC EXECUTION LOG
                    </div>
                    {activeScenario.steps.map((st, i) => (
                      <div key={i} className="flex items-start gap-2 font-mono leading-tight">
                        <span className="text-aegis-text-faint w-12 shrink-0">{st.time}</span>
                        <span className={`w-28 shrink-0 font-bold ${
                          st.status === "success" ? "text-aegis-accent" :
                          st.status === "blocked" ? "text-[#EF5350]" :
                          st.status === "warning" ? "text-aegis-copper" : "text-aegis-text-muted"
                        }`}>
                          {st.action}
                        </span>
                        <span className="text-aegis-text-muted truncate flex-1">{st.detail}</span>
                      </div>
                    ))}
                  </div>

                  {/* Merkle Hash Footer */}
                  <div className="pt-2 border-t border-aegis-border/60 flex items-center justify-between text-[9px] text-aegis-text-faint">
                    <span>MERKLE BLOCK:</span>
                    <span className="font-mono text-aegis-text-muted truncate max-w-[200px] sm:max-w-[260px]">
                      {activeScenario.merkleHash}
                    </span>
                  </div>
                </div>

              </div>
            </div>

          </div>
        </section>

        {/* 4 Core Financial Integrity Proof Points */}
        <section className="mt-16">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-px border border-aegis-border bg-aegis-border font-mono">
            <div className="bg-aegis-surface p-6">
              <div className="flex items-center justify-between text-aegis-text-muted">
                <span className="text-[11px] uppercase tracking-wider">POLICY LATENCY</span>
                <Zap className="h-4 w-4 text-aegis-accent" />
              </div>
              <div className="mt-3 text-3xl font-bold text-aegis-text-primary tabular-nums">&lt; 12ms</div>
              <p className="mt-1.5 text-xs text-aegis-text-faint">Deterministic policy engine evaluation</p>
            </div>

            <div className="bg-aegis-surface p-6">
              <div className="flex items-center justify-between text-aegis-text-muted">
                <span className="text-[11px] uppercase tracking-wider">PROVENANCE LOG</span>
                <Fingerprint className="h-4 w-4 text-aegis-accent" />
              </div>
              <div className="mt-3 text-3xl font-bold text-aegis-accent tabular-nums">HMAC-SHA256</div>
              <p className="mt-1.5 text-xs text-aegis-text-faint">Monotonic append-only tamper chain</p>
            </div>

            <div className="bg-aegis-surface p-6">
              <div className="flex items-center justify-between text-aegis-text-muted">
                <span className="text-[11px] uppercase tracking-wider">FORENSIC SIMULATION</span>
                <RotateCcw className="h-4 w-4 text-aegis-copper" />
              </div>
              <div className="mt-3 text-3xl font-bold text-aegis-copper tabular-nums">0 SIDE-EFFECTS</div>
              <p className="mt-1.5 text-xs text-aegis-text-faint">Read-only counterfactual replay</p>
            </div>

            <div className="bg-aegis-surface p-6">
              <div className="flex items-center justify-between text-aegis-text-muted">
                <span className="text-[11px] uppercase tracking-wider">TEST SUITE & SECURITY</span>
                <CheckCircle2 className="h-4 w-4 text-aegis-accent" />
              </div>
              <div className="mt-3 text-3xl font-bold text-aegis-text-primary tabular-nums">453 / 453 PASS</div>
              <p className="mt-1.5 text-xs text-aegis-text-faint">0 Critical CVEs, 100% tenant isolated</p>
            </div>
          </div>
        </section>

        {/* The Three Core Subsystems */}
        <section className="mt-20" id="subsystems">
          <div className="text-center max-w-3xl mx-auto">
            <span className="font-mono text-xs uppercase tracking-widest text-aegis-accent font-semibold">
              UNIFIED ARCHITECTURE
            </span>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-aegis-text-primary sm:text-4xl">
              Three Pillars of Autonomous Financial Governance
            </h2>
            <p className="mt-3 text-sm text-aegis-text-muted leading-relaxed font-sans">
              AEGIS replaces disjointed point-solutions with an end-to-end financial operating system designed specifically for non-deterministic AI agents.
            </p>
          </div>

          <div className="mt-12 grid gap-6 md:grid-cols-3">
            
            {/* Subsystem 01: AgentPay Guardian */}
            <article className="border border-aegis-border bg-aegis-surface p-7 rounded-sm relative flex flex-col justify-between shadow-panel hover:border-aegis-accent/50 transition-colors">
              <div>
                <div className="flex items-center justify-between border-b border-aegis-border pb-3.5">
                  <span className="font-mono text-xs uppercase tracking-widest text-aegis-accent font-bold">
                    SUBSYSTEM 01
                  </span>
                  <div className="h-8 w-8 flex items-center justify-center border border-aegis-accent/30 bg-aegis-accent/10 text-aegis-accent">
                    <Lock className="h-4 w-4" />
                  </div>
                </div>

                <h3 className="mt-5 text-xl font-bold text-aegis-text-primary tracking-tight">
                  AgentPay Guardian
                </h3>
                <p className="mt-1 font-mono text-[11px] text-aegis-text-faint uppercase">
                  Pre-Settlement Spending Governance
                </p>

                <p className="mt-4 text-xs leading-relaxed text-aegis-text-muted font-sans">
                  Deterministic spending passports, row-level PostgreSQL balance locks, quote hash integrity, and multi-sig escalation thresholds. Evaluates every intent before contacting PayPal Orders v2.
                </p>

                <div className="mt-6 space-y-2 font-mono text-[11px] text-aegis-text-muted">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-accent" />
                    <span>Cryptographic Spending Passports</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-accent" />
                    <span>Deterministic Policy Engine (&lt;12ms)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-accent" />
                    <span>Transactional Outbox & Row-Level Locks</span>
                  </div>
                </div>
              </div>

              <div className="mt-8 border-t border-aegis-border pt-4 flex items-center justify-between font-mono text-xs">
                <span className="text-aegis-text-faint">GATEWAY STATUS:</span>
                <span className="text-aegis-accent font-bold">STRICT ENFORCEMENT</span>
              </div>
            </article>

            {/* Subsystem 02: GhostPay Forensics */}
            <article className="border border-aegis-border bg-aegis-surface p-7 rounded-sm relative flex flex-col justify-between shadow-panel hover:border-aegis-copper/50 transition-colors">
              <div>
                <div className="flex items-center justify-between border-b border-aegis-border pb-3.5">
                  <span className="font-mono text-xs uppercase tracking-widest text-aegis-copper font-bold">
                    SUBSYSTEM 02
                  </span>
                  <div className="h-8 w-8 flex items-center justify-center border border-aegis-copper/30 bg-aegis-copper/10 text-aegis-copper">
                    <FileSearch className="h-4 w-4" />
                  </div>
                </div>

                <h3 className="mt-5 text-xl font-bold text-aegis-text-primary tracking-tight">
                  GhostPay Forensics
                </h3>
                <p className="mt-1 font-mono text-[11px] text-aegis-text-faint uppercase">
                  Counterfactual Replay & Anomaly Detection
                </p>

                <p className="mt-4 text-xs leading-relaxed text-aegis-text-muted font-sans">
                  Zero-side-effect forensic replay engine. Simulates counterfactual policy changes against historical agent traces, detects behavioral authorization drift, and verifies Merkle hash chains.
                </p>

                <div className="mt-6 space-y-2 font-mono text-[11px] text-aegis-text-muted">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-copper" />
                    <span>Zero-Side-Effect Sandbox Replay</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-copper" />
                    <span>Agent Spending DNA Profiling</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-copper" />
                    <span>Authorization Drift Indexing</span>
                  </div>
                </div>
              </div>

              <div className="mt-8 border-t border-aegis-border pt-4 flex items-center justify-between font-mono text-xs">
                <span className="text-aegis-text-faint">FORENSIC ENGINE:</span>
                <span className="text-aegis-copper font-bold">ISOLATED READ-ONLY</span>
              </div>
            </article>

            {/* Subsystem 03: DisputeOS */}
            <article className="border border-aegis-border bg-aegis-surface p-7 rounded-sm relative flex flex-col justify-between shadow-panel hover:border-aegis-text-primary/50 transition-colors">
              <div>
                <div className="flex items-center justify-between border-b border-aegis-border pb-3.5">
                  <span className="font-mono text-xs uppercase tracking-widest text-aegis-text-primary font-bold">
                    SUBSYSTEM 03
                  </span>
                  <div className="h-8 w-8 flex items-center justify-center border border-aegis-border bg-aegis-card text-aegis-text-primary">
                    <Scale className="h-4 w-4" />
                  </div>
                </div>

                <h3 className="mt-5 text-xl font-bold text-aegis-text-primary tracking-tight">
                  DisputeOS
                </h3>
                <p className="mt-1 font-mono text-[11px] text-aegis-text-faint uppercase">
                  Multi-Rail Dispute & Contradiction Resolution
                </p>

                <p className="mt-4 text-xs leading-relaxed text-aegis-text-muted font-sans">
                  Tenant-scoped evidence artifact storage, causal provenance graphs, automated contradiction analysis between agent logs and merchant receipts, and mandatory human-in-the-loop sign-off.
                </p>

                <div className="mt-6 space-y-2 font-mono text-[11px] text-aegis-text-muted">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-text-primary" />
                    <span>Causal Evidence Graphs</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-text-primary" />
                    <span>Contradiction Detection Engine</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-aegis-text-primary" />
                    <span>Mandatory Dual-Signature Review</span>
                  </div>
                </div>
              </div>

              <div className="mt-8 border-t border-aegis-border pt-4 flex items-center justify-between font-mono text-xs">
                <span className="text-aegis-text-faint">DECISION GATE:</span>
                <span className="text-aegis-text-primary font-bold">HUMAN-IN-THE-LOOP</span>
              </div>
            </article>

          </div>
        </section>

        {/* Platform Architecture Diagram */}
        <section className="mt-20" id="architecture">
          <div className="border border-aegis-border bg-aegis-surface p-8 shadow-panel rounded-sm">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-aegis-border pb-4">
              <div>
                <span className="font-mono text-xs text-aegis-accent uppercase font-bold tracking-wider">
                  END-TO-END TRANSACTION PIPELINE
                </span>
                <h3 className="mt-1 text-2xl font-bold text-aegis-text-primary">
                  The Zero-Trust Financial Lifecycle
                </h3>
              </div>
              <div className="font-mono text-xs text-aegis-text-muted">
                DETERMINISTIC &gt; PROBABILISTIC
              </div>
            </div>

            <div className="mt-8 grid grid-cols-1 md:grid-cols-5 gap-4 font-mono text-xs">
              
              {/* Step 1 */}
              <div className="border border-aegis-border bg-aegis-card p-4 rounded-sm">
                <div className="text-[10px] text-aegis-accent font-bold uppercase">STEP 01</div>
                <div className="mt-2 text-sm font-bold text-aegis-text-primary">Agent Intent</div>
                <p className="mt-1.5 text-[11px] text-aegis-text-muted leading-relaxed font-sans">
                  Autonomous agent invokes purchase action with cryptographic passport token.
                </p>
              </div>

              {/* Step 2 */}
              <div className="border border-aegis-accent/50 bg-aegis-accent/5 p-4 rounded-sm">
                <div className="text-[10px] text-aegis-accent font-bold uppercase">STEP 02</div>
                <div className="mt-2 text-sm font-bold text-aegis-accent">Guardian Gate</div>
                <p className="mt-1.5 text-[11px] text-aegis-text-muted leading-relaxed font-sans">
                  Evaluates velocity, merchant whitelists, budget ceiling in &lt;12ms.
                </p>
              </div>

              {/* Step 3 */}
              <div className="border border-aegis-border bg-aegis-card p-4 rounded-sm">
                <div className="text-[10px] text-aegis-copper font-bold uppercase">STEP 03</div>
                <div className="mt-2 text-sm font-bold text-aegis-copper">Atomic Lock</div>
                <p className="mt-1.5 text-[11px] text-aegis-text-muted leading-relaxed font-sans">
                  Acquires PostgreSQL row-level reservation lock. Outbox event staged.
                </p>
              </div>

              {/* Step 4 */}
              <div className="border border-aegis-border bg-aegis-card p-4 rounded-sm">
                <div className="text-[10px] text-aegis-text-primary font-bold uppercase">STEP 04</div>
                <div className="mt-2 text-sm font-bold text-aegis-text-primary">PayPal Settle</div>
                <p className="mt-1.5 text-[11px] text-aegis-text-muted leading-relaxed font-sans">
                  Orders v2 client executes capture with deterministic quote hash validation.
                </p>
              </div>

              {/* Step 5 */}
              <div className="border border-aegis-border bg-aegis-card p-4 rounded-sm">
                <div className="text-[10px] text-aegis-accent font-bold uppercase">STEP 05</div>
                <div className="mt-2 text-sm font-bold text-aegis-accent">Merkle Ledger</div>
                <p className="mt-1.5 text-[11px] text-aegis-text-muted leading-relaxed font-sans">
                  SHA-256 block chained to immutable audit log. Feed ready for GhostPay & DisputeOS.
                </p>
              </div>

            </div>
          </div>
        </section>

        {/* Developer Experience & aegis CLI Showcase */}
        <section className="mt-20" id="cli">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
            
            <div className="lg:col-span-6">
              <span className="font-mono text-xs uppercase tracking-widest text-aegis-copper font-bold">
                DEVELOPER TOOLING & SDK
              </span>
              <h2 className="mt-3 text-3xl font-bold tracking-tight text-aegis-text-primary sm:text-4xl">
                Integrated Python SDK & Unified CLI
              </h2>
              <p className="mt-4 text-sm text-aegis-text-muted leading-relaxed font-sans">
                Ship financial governance to your AI agent fleets with two lines of code. The <code className="font-mono text-aegis-text-primary bg-aegis-card px-1.5 py-0.5 border border-aegis-border">aegis</code> CLI lets site reliability engineers inspect Merkle chains, trigger zero-side-effect replays, and verify system readiness from terminal workflows.
              </p>

              <div className="mt-6 space-y-3 font-mono text-xs">
                <div className="flex items-center gap-3 border border-aegis-border bg-aegis-card p-3">
                  <span className="font-bold text-aegis-accent">$</span>
                  <span className="text-aegis-text-primary">pip install aegis-sdk</span>
                </div>
                <div className="flex items-center gap-3 border border-aegis-border bg-aegis-card p-3">
                  <span className="font-bold text-aegis-accent">$</span>
                  <span className="text-aegis-text-primary">aegis verify-chain --tenant-id 829db6b0-6566-4d6d-84e7-6fae90633723</span>
                </div>
                <div className="flex items-center gap-3 border border-aegis-border bg-aegis-card p-3">
                  <span className="font-bold text-aegis-accent">$</span>
                  <span className="text-aegis-text-primary">aegis simulate --scenario prompt-injection-escape</span>
                </div>
              </div>
            </div>

            <div className="lg:col-span-6">
              <div className="border border-aegis-border bg-aegis-surface p-5 rounded-sm shadow-panel font-mono text-xs">
                <div className="flex items-center justify-between border-b border-aegis-border pb-3 text-aegis-text-muted text-[11px]">
                  <span>PYTHON INTERFACE (LANGGRAPH / CREWAI / AUTOGEN)</span>
                  <span className="text-aegis-accent">ZERO-TRUST WRAPPER</span>
                </div>

                <pre className="mt-4 text-aegis-text-muted font-mono text-[11px] leading-relaxed overflow-x-auto">
{`from aegis_sdk import AegisClient, SpendPassport

# Initialize client with cryptographically verified tenant passport
client = AegisClient(api_key=os.environ["AEGIS_API_KEY"])
passport = client.passports.get("PASS-GPU-AUTONOMY-01")

# Intercept agent intent before PayPal settlement
intent = passport.authorize_spend(
    amount=124.50,
    currency="USD",
    merchant="api.azure.microsoft.com",
    agent_id="devops-crawler-42",
    context={"task": "gpu_cluster_scale_out"}
)

if intent.status == "APPROVED":
    # Funds safely reserved in PostgreSQL row lock
    paypal_order = client.paypal.capture_order(intent.quote_hash)
    print(f"Captured: {paypal_order.id} | Merkle: {intent.merkle_block_id}")
else:
    # Deterministic rejection - zero dollars left treasury
    raise SpendPolicyViolation(intent.rejection_reason)`}
                </pre>
              </div>
            </div>

          </div>
        </section>

        {/* Evaluator Staging Callout Bar */}
        <section className="mt-20 border border-aegis-accent bg-aegis-surface p-8 shadow-panel rounded-sm relative overflow-hidden">
          <div className="absolute top-0 right-0 h-40 w-40 bg-aegis-accent/5 rounded-full blur-2xl pointer-events-none" />
          
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative">
            <div>
              <div className="flex items-center gap-2 font-mono text-xs text-aegis-accent font-bold uppercase tracking-wider">
                <ShieldCheck className="h-4 w-4" />
                <span>READY FOR IMMEDIATE EVALUATION</span>
              </div>
              <h3 className="mt-2 text-2xl font-bold text-aegis-text-primary">
                Experience AEGIS in Action on Azure Staging
              </h3>
              <p className="mt-1.5 text-xs text-aegis-text-muted max-w-2xl font-sans">
                Full production-grade deployment running on Azure Cloud with Neon PostgreSQL v18.6, Upstash Redis v8.4.0, and isolated PayPal Sandbox Orders v2 client.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3 shrink-0">
              <Link
                href="/login"
                className="inline-flex items-center gap-2 border border-aegis-accent bg-aegis-accent px-6 py-3 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover transition-colors shadow-editorial"
              >
                <span>ENTER CONSOLE</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/status"
                className="inline-flex items-center gap-2 border border-aegis-border bg-aegis-card px-4 py-3 font-mono text-xs uppercase tracking-wider text-aegis-text-muted hover:text-aegis-text-primary transition-colors"
              >
                <span>SYSTEM HEALTH</span>
              </Link>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="mt-20 border-t border-aegis-border pt-8 pb-12 text-xs font-mono text-aegis-text-faint flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span>AEGIS // FINANCIAL OS FOR AI AGENTS</span>
            <span className="text-aegis-border">•</span>
            <span>RELEASE CANDIDATE 1</span>
            <span className="text-aegis-border">•</span>
            <span>COMMIT SHA: <strong className="text-aegis-text-muted">e3565c0</strong></span>
          </div>

          <div className="flex items-center gap-6">
            <Link href="/status" className="hover:text-aegis-accent transition-colors">
              NETWORK STATUS
            </Link>
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
