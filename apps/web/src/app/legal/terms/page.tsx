import React from "react";
import { FileText, ShieldAlert } from "lucide-react";

export default function TermsOfServicePage() {
  return (
    <div className="space-y-8 rounded-2xl border border-aegis-border bg-aegis-surface p-8 shadow-xl">
      <div className="border-b border-aegis-border pb-6">
        <div className="flex items-center gap-2 text-aegis-accent">
          <FileText className="h-6 w-6" />
          <h1 className="text-2xl font-bold text-white">Master SaaS Terms of Service</h1>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Effective Date: January 1, 2026 · Version: 2026.1 (Production Commercial Release)
        </p>
      </div>

      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-200">
        <div className="flex items-center gap-2 font-semibold text-amber-300">
          <ShieldAlert className="h-4 w-4" />
          <span>NON-CUSTODIAL FINANCIAL CONTROL PLANE BOUNDARY</span>
        </div>
        <p className="mt-1 leading-relaxed">
          AEGIS provides policy-based authorization, cryptographic replay auditing, and decision governance for autonomous AI agents. AEGIS is not a bank, money transmitter, depository institution, or payment processor. All payment settlements occur directly between Customer accounts and third-party payment rails (e.g. PayPal Sandbox/Production, Stripe). AEGIS never takes custody of, touches, or holds customer funds.
        </p>
      </div>

      <div className="space-y-6 text-xs leading-relaxed text-slate-300">
        <section>
          <h2 className="text-sm font-semibold text-white">1. Acceptance of Terms</h2>
          <p className="mt-1">
            By creating an organization, accessing the AEGIS Control Plane, issuing API keys, or connecting agent runtimes via the AEGIS SDK, you (&ldquo;Customer&rdquo; or &ldquo;User&rdquo;) agree to be bound by these Master SaaS Terms of Service (&ldquo;Terms&rdquo;). If you are entering into these Terms on behalf of a company or other legal entity, you represent that you have authority to bind such entity.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">2. Scope of Service & Platform Governance</h2>
          <p className="mt-1">
            AEGIS grants Customer a non-exclusive, non-transferable right to access and use the AEGIS Financial Black Box platform, including:
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-300">
            <li><strong>Agent Spending Passports:</strong> Deterministic budget limits, velocity restrictions, category allowlists, and human approval escalation thresholds.</li>
            <li><strong>GhostPay Replay & Simulation:</strong> Hash-chained event log reconstruction, counterfactual policy drift detection, and tamper verification.</li>
            <li><strong>DisputeOS:</strong> Evidence graph synthesis, contradiction detection, and grounded response drafting.</li>
            <li><strong>Worker Transactional Outbox:</strong> At-least-once signed outbound webhook dispatches and dead-letter queue monitoring.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">3. Customer Responsibilities for AI Agent Spending</h2>
          <p className="mt-1">
            Customer retains exclusive ownership and responsibility for configuring policy thresholds, selecting allowlisted merchant IDs, issuing spending passports, and approving human escalation requests. AEGIS enforces the exact rules configured by Customer&apos;s authorized administrators and disclaims liability for financial transactions executed within the boundaries of passports created by Customer.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">4. Third-Party Payment Providers & Sandbox Compliance</h2>
          <p className="mt-1">
            Integration with PayPal, Stripe, or other payment gateways requires Customer to maintain active accounts in good standing with those providers. Customer agrees to comply with the PayPal Acceptable Use Policy and Stripe Connected Account Agreements. Testing must be conducted against authorized sandbox credentials before enabling live payment capture.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">5. Service Level Agreement (SLA) & Availability</h2>
          <p className="mt-1">
            AEGIS commits to a 99.9% Monthly Uptime Percentage for the Core Governance API and Verification Engine. Scheduled maintenance will be announced with at least 48 hours notice via the public status page at <a href="/status" className="text-aegis-accent underline">/status</a>.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">6. Confidentiality & Security Measures</h2>
          <p className="mt-1">
            AEGIS employs state-of-the-art security controls, including HMAC-SHA256 event signing, AES-256 encryption at rest, tenant-scoped schema isolation, and comprehensive admin audit logging. AEGIS will never sell or disclose Customer transaction logs or policy configurations to third parties.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">7. Limitation of Liability</h2>
          <p className="mt-1">
            TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT SHALL AEGIS PLATFORM INC. BE LIABLE FOR ANY INDIRECT, PUNITIVE, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES ARISING OUT OF AUTONOMOUS AGENT ACTIONS OR THIRD-PARTY PAYMENT PROVIDER OUTAGES. TOTAL AGGREGATE LIABILITY SHALL NOT EXCEED THE AMOUNTS ACTUALLY PAID BY CUSTOMER IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">8. Governing Law & Jurisdiction</h2>
          <p className="mt-1">
            These Terms shall be governed by and construed in accordance with the laws of the State of Delaware, without regard to its conflict of law principles.
          </p>
        </section>
      </div>

      <div className="border-t border-aegis-border pt-4 text-xs text-slate-400">
        Questions regarding these Terms? Contact legal at <span className="font-mono text-aegis-accent">legal@aegis-platform.internal</span>.
      </div>
    </div>
  );
}
