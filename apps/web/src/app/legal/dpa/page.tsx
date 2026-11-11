import React from "react";
import { FileCheck2, ShieldCheck, Lock, Server } from "lucide-react";

export default function DataProcessingAddendumPage() {
  return (
    <div className="space-y-8 rounded-2xl border border-aegis-border bg-aegis-surface p-8 shadow-xl">
      <div className="border-b border-aegis-border pb-6">
        <div className="flex items-center gap-2 text-sky-400">
          <FileCheck2 className="h-6 w-6" />
          <h1 className="text-2xl font-bold text-white">Data Processing Addendum (DPA)</h1>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Standard Contractual Clauses & Processor Obligations · Version 2026.1
        </p>
      </div>

      <div className="rounded-xl border border-sky-500/30 bg-sky-500/10 p-4 text-xs text-sky-200">
        <div className="flex items-center gap-2 font-semibold text-sky-300">
          <ShieldCheck className="h-4 w-4" />
          <span>DATA CONTROLLER & PROCESSOR RELATIONSHIP</span>
        </div>
        <p className="mt-1 leading-relaxed">
          This Data Processing Addendum (&ldquo;DPA&rdquo;) supplements the AEGIS Master Terms of Service. Customer acts as the <strong>Data Controller</strong> and AEGIS Platform Inc. acts as the <strong>Data Processor</strong> in accordance with Article 28 of the GDPR and Section 8 of the Indian DPDPA 2023.
        </p>
      </div>

      <div className="space-y-6 text-xs leading-relaxed text-slate-300">
        <section>
          <h2 className="text-sm font-semibold text-white">1. Scope, Details of Processing & Instructions</h2>
          <p className="mt-1">
            AEGIS shall process personal data solely on documented instructions from Customer, including with respect to transfers of personal data to a third country, unless required to do so by applicable Union, Member State, or regional law. The duration, nature, purpose of processing, and types of personal data are governed by the Terms of Service.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">2. Technical and Organizational Security Measures (TOMs)</h2>
          <p className="mt-1">
            AEGIS implements and maintains rigorous technical and organizational measures to ensure a level of security appropriate to the risk:
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
              <div className="flex items-center gap-2 font-semibold text-white">
                <Lock className="h-4 w-4 text-sky-400" />
                <span>Cryptographic Hash Chaining</span>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                Every financial event is SHA-256 hash-chained to previous transactions, guaranteeing tamper-evident ledger immutability.
              </p>
            </div>

            <div className="rounded-lg border border-aegis-border bg-aegis-panel p-3">
              <div className="flex items-center gap-2 font-semibold text-white">
                <Server className="h-4 w-4 text-emerald-400" />
                <span>Multi-Tenant Schema Isolation</span>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                PostgreSQL tenant partitioning ensures zero cross-organization data leakage with deterministic tenant filters.
              </p>
            </div>
          </div>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">3. Authorized Subprocessors</h2>
          <p className="mt-1">
            Customer authorizes AEGIS to engage the following categories of subprocessors:
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left font-mono text-[11px]">
              <thead className="border-b border-aegis-border bg-aegis-panel text-slate-400">
                <tr>
                  <th className="p-2">Subprocessor</th>
                  <th className="p-2">Purpose</th>
                  <th className="p-2">Location</th>
                  <th className="p-2">Safeguards</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-aegis-border">
                <tr>
                  <td className="p-2 font-semibold text-white">Stripe Inc.</td>
                  <td className="p-2">SaaS Subscription & Usage Metering</td>
                  <td className="p-2">USA / Global</td>
                  <td className="p-2">PCI DSS Level 1 / EU SCCs</td>
                </tr>
                <tr>
                  <td className="p-2 font-semibold text-white">PayPal Holdings Inc.</td>
                  <td className="p-2">Sandbox & Production Merchant Capture</td>
                  <td className="p-2">USA / EU</td>
                  <td className="p-2">PCI DSS Level 1 / BCRs</td>
                </tr>
                <tr>
                  <td className="p-2 font-semibold text-white">AWS / Cloud Hosting</td>
                  <td className="p-2">Container Hosting & KMS Encryption</td>
                  <td className="p-2">EU (Frankfurt) / US</td>
                  <td className="p-2">SOC 2 Type II / ISO 27001</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">4. Security Incident & Breach Notification</h2>
          <p className="mt-1">
            AEGIS shall notify Customer without undue delay and in any event within forty-eight (48) hours of becoming aware of a confirmed Personal Data Breach affecting Customer personal data. AEGIS will provide detailed analysis of affected records and remedial steps taken.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">5. Audit Rights & Compliance Verifications</h2>
          <p className="mt-1">
            AEGIS makes available to Customer all information necessary to demonstrate compliance with Article 28 of the GDPR, including SOC 2 Type II summary reports, cryptographic hash chain verification toolchains, and annual third-party penetration test attestations.
          </p>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-white">6. Data Deletion and Return (Crypto-Shredding)</h2>
          <p className="mt-1">
            Upon termination of the Services or upon Customer request via the Control Plane, AEGIS shall, at the choice of Customer, delete (via cryptographic key destruction) or return all personal data to Customer, and delete existing copies unless Union or Member State law requires retention.
          </p>
        </section>
      </div>

      <div className="border-t border-aegis-border pt-4 text-xs text-slate-400">
        Signed on behalf of AEGIS Platform Inc. · Trust & Security Officer
      </div>
    </div>
  );
}
