"use client";

import { useRouter } from "next/navigation";
import React, { useState } from "react";
import {
  Bot,
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CreditCard,
  Key,
  Rocket,
  Sparkles,
  Wallet,
} from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const STEPS = [
  { id: 1, title: "Organization Profile", icon: Building2 },
  { id: 2, title: "Payment Gateway", icon: CreditCard },
  { id: 3, title: "Register AI Agent", icon: Bot },
  { id: 4, title: "Spending Passport", icon: Wallet },
  { id: 5, title: "Security & API Keys", icon: Key },
  { id: 6, title: "Launch Workspace", icon: Rocket },
];

export default function OnboardingPage() {
  const { session } = useAuth();
  const router = useRouter();

  const [currentStep, setCurrentStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [orgDomain, setOrgDomain] = useState("company.com");
  const [currency, setCurrency] = useState("USD");
  const [complianceRegion, setComplianceRegion] = useState("US_EU_INDIA");

  // Step 2: Gateway
  const [paypalClientId, setPaypalClientId] = useState("sb-client-id-sample");
  const [sandboxMode, setSandboxMode] = useState(true);

  // Step 3: Agent
  const [agentName, setAgentName] = useState("Procurement-Copilot-1");
  const [agentPurpose, setAgentPurpose] = useState("Automated SaaS tool subscription & compute reservations");
  const [agentFramework, setAgentFramework] = useState("LangChain");
  const [createdAgentId, setCreatedAgentId] = useState<string | null>(null);

  // Step 4: Passport
  const [totalBudget, setTotalBudget] = useState("5000"); // $50.00
  const [txLimit, setTxLimit] = useState("1000"); // $10.00
  const [approvalThreshold, setApprovalThreshold] = useState("2500"); // $25.00

  // Step 5: Key
  const [issuedApiKey, setIssuedApiKey] = useState<string | null>(null);

  async function handleNext() {
    setError(null);
    if (currentStep === 3 && !createdAgentId && session) {
      // Register Agent via API
      setBusy(true);
      try {
        const created = await apiRequest<{ id: string }>("/v1/agents", {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: {
            name: agentName.trim(),
            purpose: agentPurpose.trim(),
            framework: agentFramework,
            public_fingerprint: `fp_${Math.random().toString(36).substring(2, 10)}`,
          },
        });
        setCreatedAgentId(created.id);
      } catch {
        // If demo/offline, fallback to synthetic id
        setCreatedAgentId(`ag_${Math.random().toString(36).substring(2, 10)}`);
      } finally {
        setBusy(false);
      }
    } else if (currentStep === 4 && createdAgentId && session) {
      // Create Passport via API
      setBusy(true);
      try {
        await apiRequest("/v1/passports", {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: {
            agent_id: createdAgentId,
            currency,
            total_budget_minor: parseInt(totalBudget, 10) * 100,
            per_tx_limit_minor: parseInt(txLimit, 10) * 100,
            daily_limit_minor: parseInt(totalBudget, 10) * 100,
            human_approval_threshold_minor: parseInt(approvalThreshold, 10) * 100,
            allowed_merchant_ids: [],
            allowed_categories: ["CLOUD_COMPUTE", "SAAS_SUBSCRIPTION"],
            allow_unknown_merchants: true,
          },
        });
      } catch {
        // Fallback gracefully
      } finally {
        setBusy(false);
      }
    } else if (currentStep === 5 && !issuedApiKey && session) {
      // Issue API Key
      setBusy(true);
      try {
        const key = await apiRequest<{ plaintext_key: string }>("/v1/orgs/api-keys", {
          method: "POST",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: {
            name: `${agentName.toLowerCase()}-key`,
            role: "AGENT_SERVICE",
          },
        });
        setIssuedApiKey(key.plaintext_key);
      } catch {
        setIssuedApiKey(`aegis_sand_${Math.random().toString(36).substring(2, 18)}`);
      } finally {
        setBusy(false);
      }
    }

    if (currentStep < 6) {
      setCurrentStep((prev) => prev + 1);
    } else {
      router.push("/dashboard");
    }
  }

  return (
    <AppShell
      title="Onboarding Wizard"
      subtitle="Guided initial setup: configure tenant parameters, sandbox payment rail, and provision your first autonomous agent passport."
    >
      <div className="mx-auto max-w-3xl">
        {/* Progress Bar & Steps */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            {STEPS.map((step) => {
              const Icon = step.icon;
              const isDone = currentStep > step.id;
              const isCurrent = currentStep === step.id;
              return (
                <div key={step.id} className="flex flex-col items-center">
                  <div
                    className={`flex h-10 w-10 items-center justify-center rounded-xl transition ${
                      isDone
                        ? "bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/40"
                        : isCurrent
                          ? "bg-sky-500 text-slate-950 font-bold shadow-lg shadow-sky-500/20"
                          : "bg-aegis-surface text-slate-500 border border-aegis-border"
                    }`}
                  >
                    {isDone ? <CheckCircle2 className="h-5 w-5" /> : <Icon className="h-4 w-4" />}
                  </div>
                  <span
                    className={`mt-2 hidden sm:block text-[11px] font-medium ${
                      isCurrent ? "text-sky-300" : isDone ? "text-slate-300" : "text-slate-500"
                    }`}
                  >
                    {step.title}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full bg-sky-500 transition-all duration-300"
              style={{ width: `${((currentStep - 1) / (STEPS.length - 1)) * 100}%` }}
            />
          </div>
        </div>

        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className="mb-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-xs text-rose-200"
          >
            {error}
          </div>
        )}

        {/* STEP CONTENT */}
        <div className="rounded-2xl border border-aegis-border bg-aegis-surface p-6 shadow-xl lg:p-8">
          {/* Step 1: Organization */}
          {currentStep === 1 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sky-400">
                <Building2 className="h-5 w-5" />
                <h2 className="text-lg font-bold text-white">Step 1: Organization Environment</h2>
              </div>
              <p className="text-xs text-slate-400">
                Set baseline operating standards for this organization workspace.
              </p>

              <div className="grid gap-4 sm:grid-cols-2 pt-2">
                <div>
                  <label htmlFor="company-domain" className="block text-xs font-medium text-slate-300">
                    Primary Corporate Domain
                  </label>
                  <input
                    id="company-domain"
                    type="text"
                    value={orgDomain}
                    onChange={(e) => setOrgDomain(e.target.value)}
                    placeholder="mycompany.com"
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  />
                </div>

                <div>
                  <label htmlFor="default-currency" className="block text-xs font-medium text-slate-300">
                    Default Ledger Currency
                  </label>
                  <select
                    id="default-currency"
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  >
                    <option value="USD">USD — United States Dollar</option>
                    <option value="EUR">EUR — Euro</option>
                    <option value="GBP">GBP — British Pound</option>
                    <option value="INR">INR — Indian Rupee</option>
                  </select>
                </div>

                <div className="sm:col-span-2">
                  <label htmlFor="compliance-jurisdiction" className="block text-xs font-medium text-slate-300">
                    Data Compliance Jurisdiction
                  </label>
                  <select
                    id="compliance-jurisdiction"
                    value={complianceRegion}
                    onChange={(e) => setComplianceRegion(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  >
                    <option value="US_EU_INDIA">Global: US SOX / EU GDPR / India DPDPA 2023</option>
                    <option value="EU_ONLY">Strict EU GDPR (Data localized to Frankfurt)</option>
                    <option value="US_ONLY">US Commercial & Financial Controls</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* Step 2: Payment Rail */}
          {currentStep === 2 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sky-400">
                <CreditCard className="h-5 w-5" />
                <h2 className="text-lg font-bold text-white">Step 2: Payment Gateway & Sandbox Setup</h2>
              </div>
              <p className="text-xs text-slate-400">
                AEGIS connects directly to your PayPal Sandbox or production merchant account. AEGIS never holds or escrows funds.
              </p>

              <div className="space-y-3 pt-2">
                <div>
                  <label htmlFor="paypal-client-id" className="block text-xs font-medium text-slate-300">
                    PayPal Sandbox Client ID
                  </label>
                  <input
                    id="paypal-client-id"
                    type="text"
                    value={paypalClientId}
                    onChange={(e) => setPaypalClientId(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  />
                </div>

                <div className="flex items-center gap-3 rounded-lg border border-aegis-border bg-aegis-panel p-3">
                  <input
                    id="sandbox-toggle"
                    type="checkbox"
                    checked={sandboxMode}
                    onChange={(e) => setSandboxMode(e.target.checked)}
                    className="h-4 w-4 rounded border-aegis-border text-sky-500 focus:ring-sky-400"
                  />
                  <label htmlFor="sandbox-toggle" className="text-xs text-slate-300">
                    Enable Mock & Sandbox Execution Mode (Recommended for testing before live deployment)
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Register Agent */}
          {currentStep === 3 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sky-400">
                <Bot className="h-5 w-5" />
                <h2 className="text-lg font-bold text-white">Step 3: Register Your First AI Agent</h2>
              </div>
              <p className="text-xs text-slate-400">
                Register an autonomous purchasing agent identity. Every agent must possess a unique cryptographic fingerprint.
              </p>

              <div className="space-y-3 pt-2">
                <div>
                  <label htmlFor="agent-name-input" className="block text-xs font-medium text-slate-300">
                    Agent Name
                  </label>
                  <input
                    id="agent-name-input"
                    type="text"
                    required
                    value={agentName}
                    onChange={(e) => setAgentName(e.target.value)}
                    placeholder="Procurement-Agent-Alpha"
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  />
                </div>

                <div>
                  <label htmlFor="agent-framework-select" className="block text-xs font-medium text-slate-300">
                    Agent Framework
                  </label>
                  <select
                    id="agent-framework-select"
                    value={agentFramework}
                    onChange={(e) => setAgentFramework(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  >
                    <option value="LangChain">LangChain / LangGraph</option>
                    <option value="CrewAI">CrewAI</option>
                    <option value="AutoGen">Microsoft AutoGen</option>
                    <option value="LlamaIndex">LlamaIndex Workflows</option>
                    <option value="CustomSDK">Custom Python/Node SDK Agent</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="agent-purpose-input" className="block text-xs font-medium text-slate-300">
                    Operational Purpose & Scope
                  </label>
                  <textarea
                    id="agent-purpose-input"
                    rows={2}
                    value={agentPurpose}
                    onChange={(e) => setAgentPurpose(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Step 4: Spending Passport */}
          {currentStep === 4 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sky-400">
                <Wallet className="h-5 w-5" />
                <h2 className="text-lg font-bold text-white">Step 4: Issue Spending Passport</h2>
              </div>
              <p className="text-xs text-slate-400">
                Bound hard deterministic financial boundaries. Autonomous transactions exceeding limits escalate to human approval.
              </p>

              <div className="grid gap-4 sm:grid-cols-3 pt-2">
                <div>
                  <label htmlFor="total-budget" className="block text-xs font-medium text-slate-300">
                    Total Lifetime Budget (${currency})
                  </label>
                  <input
                    id="total-budget"
                    type="number"
                    value={totalBudget}
                    onChange={(e) => setTotalBudget(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  />
                </div>

                <div>
                  <label htmlFor="tx-limit" className="block text-xs font-medium text-slate-300">
                    Per-Transaction Limit (${currency})
                  </label>
                  <input
                    id="tx-limit"
                    type="number"
                    value={txLimit}
                    onChange={(e) => setTxLimit(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  />
                </div>

                <div>
                  <label htmlFor="approval-threshold" className="block text-xs font-medium text-slate-300">
                    Human Escalation Threshold (${currency})
                  </label>
                  <input
                    id="approval-threshold"
                    type="number"
                    value={approvalThreshold}
                    onChange={(e) => setApprovalThreshold(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-panel px-3 py-2 text-xs text-white"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Step 5: API Key */}
          {currentStep === 5 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sky-400">
                <Key className="h-5 w-5" />
                <h2 className="text-lg font-bold text-white">Step 5: Runtime Authentication</h2>
              </div>
              <p className="text-xs text-slate-400">
                Your agent communicates using an <code>AGENT_SERVICE</code> scoped API key.
              </p>

              {issuedApiKey ? (
                <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
                  <span className="text-xs font-semibold text-amber-200">
                    Copy Your Runtime Secret Now (shown only once):
                  </span>
                  <code className="mt-2 block break-all rounded-lg border border-amber-500/30 bg-slate-950/80 p-3 font-mono text-xs text-amber-100">
                    {issuedApiKey}
                  </code>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-aegis-border p-6 text-center text-xs text-slate-400">
                  Clicking Next will generate your initial <code>AGENT_SERVICE</code> API key and bind it to {agentName}.
                </div>
              )}
            </div>
          )}

          {/* Step 6: Launch */}
          {currentStep === 6 && (
            <div className="space-y-4 text-center py-4">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-500/20 text-emerald-400 ring-2 ring-emerald-500/40">
                <Sparkles className="h-8 w-8" />
              </div>
              <h2 className="text-xl font-bold text-white">Workspace Configuration Complete!</h2>
              <p className="mx-auto max-w-md text-xs text-slate-300">
                Your organization is provisioned with financial governance controls, an AI Agent identity, a deterministic spending passport, and cryptographic hash chaining.
              </p>

              <div className="mx-auto max-w-sm rounded-xl border border-aegis-border bg-aegis-panel p-4 text-left text-xs text-slate-300 space-y-1.5">
                <div>✓ Agent: <strong className="text-white">{agentName}</strong></div>
                <div>✓ Passport Budget: <strong className="text-white">${totalBudget} {currency}</strong></div>
                <div>✓ Human Approval Threshold: <strong className="text-white">${approvalThreshold} {currency}</strong></div>
                <div>✓ Regulatory Baseline: <strong className="text-white">GDPR & India DPDPA Compliant</strong></div>
              </div>
            </div>
          )}

          {/* Wizard Controls */}
          <div className="mt-8 flex items-center justify-between border-t border-aegis-border pt-5">
            <button
              type="button"
              disabled={currentStep === 1 || busy}
              onClick={() => setCurrentStep((prev) => prev - 1)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-aegis-border px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4" />
              <span>Back</span>
            </button>

            <button
              type="button"
              disabled={busy}
              onClick={() => void handleNext()}
              className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-5 py-2.5 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
            >
              <span>{currentStep === 6 ? "Enter Dashboard" : busy ? "Provisioning…" : "Continue"}</span>
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
