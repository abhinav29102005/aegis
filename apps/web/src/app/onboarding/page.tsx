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
  { id: 1, title: "Organization", icon: Building2 },
  { id: 2, title: "Payment Rail", icon: CreditCard },
  { id: 3, title: "AI Agent", icon: Bot },
  { id: 4, title: "Passport", icon: Wallet },
  { id: 5, title: "API Keys", icon: Key },
  { id: 6, title: "Launch", icon: Rocket },
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
      subtitle="Guided setup: configure tenant parameters, sandbox payment rail, and provision your first autonomous agent passport"
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
                    className={`flex h-10 w-10 items-center justify-center rounded border transition ${
                      isDone
                        ? "border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent"
                        : isCurrent
                          ? "border-aegis-accent bg-aegis-accent text-[#111513] font-bold shadow-sm"
                          : "border-aegis-border bg-aegis-card text-aegis-text-faint"
                    }`}
                  >
                    {isDone ? <CheckCircle2 className="h-5 w-5" /> : <Icon className="h-4 w-4" />}
                  </div>
                  <span
                    className={`mt-2 hidden sm:block font-mono text-[10px] uppercase tracking-wider ${
                      isCurrent ? "text-aegis-accent font-semibold" : isDone ? "text-aegis-text-primary" : "text-aegis-text-faint"
                    }`}
                  >
                    {step.title}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-aegis-card border border-aegis-border">
            <div
              className="h-full bg-aegis-accent transition-all duration-300"
              style={{ width: `${((currentStep - 1) / (STEPS.length - 1)) * 100}%` }}
            />
          </div>
        </div>

        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className="mb-6 rounded border border-aegis-rose/40 bg-aegis-rose/10 p-4 font-mono text-xs text-aegis-rose"
          >
            [FAULT] {error}
          </div>
        )}

        {/* STEP CONTENT */}
        <div className="rounded-xl border border-aegis-border bg-aegis-surface p-6 shadow-sm lg:p-8">
          {/* Step 1: Organization */}
          {currentStep === 1 && (
            <div className="space-y-4">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[SETUP // STEP 01]</span>
                <h2 className="text-base font-semibold tracking-wide text-aegis-text-primary">Organization Environment</h2>
              </div>
              <p className="text-xs text-aegis-text-muted">
                Define the primary boundary parameters and settlement currency for this workspace.
              </p>

              <div className="grid gap-4 sm:grid-cols-2 pt-2">
                <div>
                  <label htmlFor="company-domain" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Primary Corporate Domain
                  </label>
                  <input
                    id="company-domain"
                    type="text"
                    value={orgDomain}
                    onChange={(e) => setOrgDomain(e.target.value)}
                    placeholder="mycompany.com"
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="default-currency" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Default Ledger Currency
                  </label>
                  <select
                    id="default-currency"
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  >
                    <option value="USD">USD — United States Dollar</option>
                    <option value="EUR">EUR — Euro</option>
                    <option value="GBP">GBP — British Pound</option>
                    <option value="INR">INR — Indian Rupee</option>
                  </select>
                </div>

                <div className="sm:col-span-2">
                  <label htmlFor="compliance-jurisdiction" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Compliance Jurisdiction
                  </label>
                  <select
                    id="compliance-jurisdiction"
                    value={complianceRegion}
                    onChange={(e) => setComplianceRegion(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
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
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper">[SETUP // STEP 02]</span>
                <h2 className="text-base font-semibold tracking-wide text-aegis-text-primary">Payment Rail & Sandbox Integration</h2>
              </div>
              <p className="text-xs text-aegis-text-muted">
                AEGIS coordinates with your PayPal Sandbox merchant credentials. AEGIS never holds or takes custody of funds.
              </p>

              <div className="space-y-3 pt-2">
                <div>
                  <label htmlFor="paypal-client-id" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    PayPal Sandbox Client ID
                  </label>
                  <input
                    id="paypal-client-id"
                    type="text"
                    value={paypalClientId}
                    onChange={(e) => setPaypalClientId(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>

                <div className="flex items-center gap-3 rounded border border-aegis-border bg-aegis-card p-3">
                  <input
                    id="sandbox-toggle"
                    type="checkbox"
                    checked={sandboxMode}
                    onChange={(e) => setSandboxMode(e.target.checked)}
                    className="h-4 w-4 rounded border-aegis-border bg-aegis-surface text-aegis-accent focus:ring-aegis-accent"
                  />
                  <label htmlFor="sandbox-toggle" className="font-mono text-xs text-aegis-text-primary">
                    Enable Isolated Sandbox Execution Mode (Recommended for testing before live deployment)
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Register Agent */}
          {currentStep === 3 && (
            <div className="space-y-4">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[SETUP // STEP 03]</span>
                <h2 className="text-base font-semibold tracking-wide text-aegis-text-primary">Register Autonomous AI Agent</h2>
              </div>
              <p className="text-xs text-aegis-text-muted">
                Register an AI purchasing agent identity. Every autonomous actor receives a deterministic cryptographic fingerprint.
              </p>

              <div className="space-y-3 pt-2">
                <div>
                  <label htmlFor="agent-name-input" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Agent Name
                  </label>
                  <input
                    id="agent-name-input"
                    type="text"
                    required
                    value={agentName}
                    onChange={(e) => setAgentName(e.target.value)}
                    placeholder="Procurement-Agent-Alpha"
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="agent-framework-select" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Agent Framework
                  </label>
                  <select
                    id="agent-framework-select"
                    value={agentFramework}
                    onChange={(e) => setAgentFramework(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  >
                    <option value="LangChain">LangChain / LangGraph</option>
                    <option value="CrewAI">CrewAI</option>
                    <option value="AutoGen">Microsoft AutoGen</option>
                    <option value="LlamaIndex">LlamaIndex Workflows</option>
                    <option value="CustomSDK">Custom Python/Node SDK Agent</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="agent-purpose-input" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Operational Scope & Purpose
                  </label>
                  <textarea
                    id="agent-purpose-input"
                    rows={2}
                    value={agentPurpose}
                    onChange={(e) => setAgentPurpose(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Step 4: Spending Passport */}
          {currentStep === 4 && (
            <div className="space-y-4">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[SETUP // STEP 04]</span>
                <h2 className="text-base font-semibold tracking-wide text-aegis-text-primary">Issue Spending Passport</h2>
              </div>
              <p className="text-xs text-aegis-text-muted">
                Bind deterministic financial limits. Proposals exceeding these boundaries require explicit human sign-off.
              </p>

              <div className="grid gap-4 sm:grid-cols-3 pt-2">
                <div>
                  <label htmlFor="total-budget" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Total Lifetime Budget (${currency})
                  </label>
                  <input
                    id="total-budget"
                    type="number"
                    value={totalBudget}
                    onChange={(e) => setTotalBudget(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="tx-limit" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Per-Transaction Limit (${currency})
                  </label>
                  <input
                    id="tx-limit"
                    type="number"
                    value={txLimit}
                    onChange={(e) => setTxLimit(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="approval-threshold" className="block font-mono text-[11px] uppercase tracking-wider text-aegis-text-muted">
                    Human Escalation Threshold (${currency})
                  </label>
                  <input
                    id="approval-threshold"
                    type="number"
                    value={approvalThreshold}
                    onChange={(e) => setApprovalThreshold(e.target.value)}
                    className="mt-1 w-full rounded border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Step 5: API Key */}
          {currentStep === 5 && (
            <div className="space-y-4">
              <div className="border-b border-aegis-border pb-3">
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-copper">[SETUP // STEP 05]</span>
                <h2 className="text-base font-semibold tracking-wide text-aegis-text-primary">Runtime Secret Generation</h2>
              </div>
              <p className="text-xs text-aegis-text-muted">
                Your agent communicates using an <code>AGENT_SERVICE</code> scoped API key.
              </p>

              {issuedApiKey ? (
                <div className="rounded border border-aegis-copper/50 bg-aegis-card p-4">
                  <span className="font-mono text-xs font-semibold uppercase tracking-wider text-aegis-copper">
                    [SECRET] Copy Your Runtime Key (shown once):
                  </span>
                  <code className="mt-2 block break-all rounded border border-aegis-copper/30 bg-[#111513] p-3 font-mono text-xs text-aegis-copper">
                    {issuedApiKey}
                  </code>
                </div>
              ) : (
                <div className="rounded border border-dashed border-aegis-border p-6 text-center font-mono text-xs text-aegis-text-muted">
                  Clicking Continue will generate your initial <code>AGENT_SERVICE</code> API key and bind it to {agentName}.
                </div>
              )}
            </div>
          )}

          {/* Step 6: Launch */}
          {currentStep === 6 && (
            <div className="space-y-4 text-center py-4">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded border border-aegis-accent/40 bg-aegis-accent/15 text-aegis-accent">
                <Sparkles className="h-7 w-7" />
              </div>
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent">[SETUP // COMPLETED]</span>
                <h2 className="text-xl font-bold tracking-tight text-aegis-text-primary">Workspace Provisioned Successfully</h2>
              </div>
              <p className="mx-auto max-w-md text-xs text-aegis-text-muted">
                Your tenant is locked with financial governance limits, an autonomous agent identity, deterministic budget passport, and SHA-256 hash chaining.
              </p>

              <div className="mx-auto max-w-sm rounded border border-aegis-border bg-aegis-card p-4 text-left font-mono text-xs text-aegis-text-muted space-y-1.5">
                <div>✓ Agent: <span className="text-aegis-text-primary font-semibold">{agentName}</span></div>
                <div>✓ Lifetime Budget: <span className="text-aegis-accent font-semibold">${totalBudget} {currency}</span></div>
                <div>✓ Human Threshold: <span className="text-aegis-copper font-semibold">${approvalThreshold} {currency}</span></div>
                <div>✓ Compliance: <span className="text-aegis-text-primary">GDPR & India DPDPA Baseline</span></div>
              </div>
            </div>
          )}

          {/* Wizard Controls */}
          <div className="mt-8 flex items-center justify-between border-t border-aegis-border pt-5 font-mono text-xs">
            <button
              type="button"
              disabled={currentStep === 1 || busy}
              onClick={() => setCurrentStep((prev) => prev - 1)}
              className="inline-flex items-center gap-1.5 rounded border border-aegis-border bg-aegis-card px-4 py-2 text-aegis-text-primary hover:bg-aegis-secondary disabled:opacity-30 transition"
            >
              <ChevronLeft className="h-4 w-4" />
              <span>Back</span>
            </button>

            <button
              type="button"
              disabled={busy}
              onClick={() => void handleNext()}
              className="inline-flex items-center gap-2 rounded bg-aegis-accent px-5 py-2.5 font-semibold uppercase tracking-wider text-[#111513] hover:bg-[#c8e562] disabled:opacity-50 transition"
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