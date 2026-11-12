import React from "react";
import { Shield, CheckCircle } from "lucide-react";

export default function PrivacyPolicyPage() {
  return (
    <div className="space-y-8 rounded-2xl border border-aegis-border bg-aegis-surface p-8 shadow-xl">
      <div className="border-b border-aegis-border pb-6">
        <div className="flex items-center gap-2 text-sky-400">
          <Shield className="h-6 w-6" />
          <h1 className="text-2xl font-bold text-white">Global Privacy & Data Protection Policy</h1>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Effective Date: January 1, 2026 · Compliant with GDPR (EU/UK), CCPA/CPRA, and India DPDPA 2023
        </p>
      </div>

      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-xs text-emerald-200">
        <div className="flex items-center gap-2 font-semibold text-emerald-300">
          <CheckCircle className="h-4 w-4" />
          <span>ZERO CARDHOLDER PAN/CVV STORAGE COMMITMENT</span>
        </div>
        <p className="mt-1 leading-relaxed">
          AEGIS strictly enforces a non-custodial data posture: We do not process, collect, or store raw primary account numbers (PAN), credit/debit card numbers, or card verification values (CVV). All direct payment instrument tokenization is conducted securely by PCI DSS Level 1 certified providers (PayPal / Stripe).
        </p>
      </div>

      <div className="space-y-6 text-xs leading-relaxed text-slate-300">
        <section>
          <h2 className="text-sm font-semibold text-white">1. Introduction & Regulatory Scope</h2>
          <p className="mt-1">
            AEGIS Platform Inc. (&ldquo;AEGIS&rdquo;, &ldquo;we&rdquo;, &ldquo;our&rdquo;) is committed to transparent, lawful, and secure processing of personal data. This Privacy Policy details our practices in compliance with the General Data Protection Regulation (GDPR, Regulation (EU) 2016/679), the UK Data Protection Act 2018, the California Consumer Privacy Act (CCPA/CPRA), and the Indian Digital Personal Data Protection Act (DPDPA 2023).
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">2. Categories of Data Collected</h2>
          <ul className="mt-2 list-disc space-y-1.5 pl-5">
            <li><strong>User Account Information:</strong> Name, work email address, hashed passwords, organization association, and assigned canonical RBAC roles.</li>
            <li><strong>Agent & Governance Metadata:</strong> Autonomous agent identifiers, public fingerprints, spending passports, currency preferences, and approval thresholds.</li>
            <li><strong>Cryptographic Financial Event Logs:</strong> Hash-chained event sequences, timestamps, merchant domain identifiers, order IDs, and approval decisions.</li>
            <li><strong>System Telemetry & Audit Logs:</strong> Admin session logins, API key rotation timestamps, IP addresses for security fraud detection, and outbound webhook delivery status codes.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">3. Legal Basis for Processing (GDPR Art. 6 & DPDPA Sec. 4)</h2>
          <p className="mt-1">
            We process Customer data exclusively based on: (a) Performance of Contract to provide the AEGIS governance control plane; (b) Compliance with legal and financial regulatory obligations; and (c) Legitimate Interest in maintaining cryptographic audit chain integrity and preventing automated agent fraud.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">4. Self-Serve Data Subject Rights (Portability & Erasure)</h2>
          <p className="mt-1">
            We provide self-service tooling within the AEGIS Settings console for all data subjects:
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li><strong>Right of Access & Portability:</strong> On-demand export of all tenant records, policies, and event timelines in machine-readable JSON and CSV formats via <code>/v1/privacy/export</code>.</li>
            <li><strong>Right to Erasure & Crypto-Shredding (GAP-024):</strong> Irreversible destruction of tenant encryption keys via <code>/v1/privacy/erasure</code>, rendering all historical audit logs unreadable and initiating database sanitization.</li>
            <li><strong>Right to Rectification:</strong> Update organization profiles, member identities, and contact information directly in the workspace portal.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">5. Data Retention & Cryptographic Immutability</h2>
          <p className="mt-1">
            Hash-chained financial event logs are retained for the duration of the customer subscription plus mandatory regulatory retention periods (up to 7 years for financial tax compliance). Upon organization offboarding or explicit erasure request, encryption keys are destroyed immediately.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">6. Security Measures & Encryption Standards</h2>
          <p className="mt-1">
            We implement comprehensive technical and organizational measures (TOMs): TLS 1.3 transit encryption, AES-256 database volume encryption, SHA-256 password salting, HMAC-SHA256 event chaining, and tenant-isolated relational partitions.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">7. Data Protection Officer (DPO) Inquiries</h2>
          <p className="mt-1">
            For inquiries regarding GDPR or India DPDPA compliance, or to exercise data rights, contact our Data Protection Officer at:
          </p>
          <div className="mt-2 rounded-lg border border-aegis-border bg-aegis-panel p-3 font-mono text-[11px] text-sky-300">
            Data Protection Officer: dpo@aegis-platform.internal<br />
            AEGIS Platform Inc. Trust & Compliance Office<br />
            Jurisdiction: Delaware, USA & European Union Representative
          </div>
        </section>
      </div>
    </div>
  );
}
