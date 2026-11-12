# AEGIS Privacy Policy

**Effective Date:** November 12, 2026  
**Last Updated:** November 12, 2026  
**Platform:** AEGIS (*Agentic Enforcement, Governance and Investigation System*)

AEGIS Platform Inc. ("AEGIS", "we", "us", or "our") is committed to protecting the privacy and security of your data. This Privacy Policy describes how we collect, use, store, and disclose information when you access our website, use the AEGIS API control plane, install AEGIS client SDKs, or deploy autonomous AI agents governed by our platform.

---

## 1. Scope & Roles Under Data Protection Laws

Depending on the context of data processing, AEGIS acts as:
- **Data Controller**: For user account registration, billing contacts, login credentials, and direct communications with organizational users.
- **Data Processor / Service Provider**: For transaction metadata, agent telemetry, spending passport configurations, and dispute evidence uploaded or processed by Customer through the AEGIS platform. Our processing of such data is governed by our [Data Processing Addendum (DPA)](DATA_PROCESSING_ADDENDUM.md).

---

## 2. Information We Collect

### 2.1. Account & Identity Information
- **User Profile Data**: Full name, business email address, role, and organization affiliation.
- **Authentication Credentials**: Hashed passwords (stored using PBKDF2-SHA256 with cryptographically random salts), multi-factor tokens, and session identifiers. We never store plaintext passwords.
- **API Keys & Machine Identities**: One-time generated API keys (stored solely as salted SHA-256 hashes), service account profiles, and public fingerprints of connected AI agents.

### 2.2. Transaction & Agent Governance Telemetry
- **Agent Metadata**: Agent IDs, names, frameworks (e.g., LangGraph, AutoGen, custom), and operational purpose descriptions.
- **Purchase Proposals & Quotes**: Spend proposals, requested amounts in minor currency units (e.g., cents), currency codes (ISO 4217), merchant IDs, merchant names, merchant categories, line-item descriptions, and operational rationale.
- **Spending Passports & Policies**: Budget limits, per-transaction thresholds, velocity rules, and human approval escalation limits.
- **Ledger Records**: Cryptographically linked `FinancialEvent` records, correlation IDs (`X-Correlation-Id`), timestamps, and state transitions.

> [!IMPORTANT]
> **No Sensitive Payment Card Data**: AEGIS does **not** collect, process, or store payment card numbers (PANs), CVVs, expiration dates, or bank account login credentials. All payment checkout and credential tokenization are conducted directly by PCI-DSS certified payment processors (e.g., PayPal Sandbox / Live).

### 2.3. DisputeOS Evidence Artifacts
- Dispute case metadata, reason codes, dispute amounts, and processor dispute identifiers.
- Uploaded evidence artifacts, including order invoices, carrier tracking receipts, customer service transcripts, and fulfillment confirmations. Evidence artifacts are hashed (SHA-256) upon ingestion to ensure tamper-evident provenance.

### 2.4. Technical & Log Data
- IP addresses, browser user agent strings, HTTP access logs, API response latency, and crash telemetry.

---

## 3. How We Use Collected Information

We process collected information to:
1. **Provide and Operate the Platform**: Authenticate users, execute deterministic policy evaluation via AgentPay Guardian, allocate atomic budgets, and coordinate checkout sessions.
2. **Ensure Forensic Integrity**: Maintain the immutable, SHA-256 hash-chained financial ledger, verify event provenance, and enable read-only forensic replays via GhostPay.
3. **Facilitate Dispute Resolution**: Structure evidence graphs, detect factual contradictions, and draft response summaries in DisputeOS.
4. **Security & Abuse Prevention**: Detect unauthorized spending, investigate security incidents, enforce RBAC permissions, and block malicious prompt-injection evasion attempts.
5. **Regulatory Compliance**: Meet statutory financial reporting, record-keeping, and audit requirements.

---

## 4. Information Sharing & Sub-Processors

We do not sell, rent, or monetize your personal or transaction data. We share data only with:
- **Authorized Cloud Infrastructure**: Encrypted database hosting, object storage, and compute environments (e.g., AWS, GCP) operating under strict data protection agreements.
- **Payment Processors**: External payment networks (such as PayPal) to transmit order references, verify captures, and submit customer-approved dispute evidence.
- **Legal & Regulatory Authorities**: When required by valid legal process, subpoena, or applicable financial regulation.

---

## 5. Cryptographic Proof Chains & Data Immutability

AEGIS incorporates an immutable hash-chained event ledger (`FinancialEvent`). Each financial decision, policy evaluation, and checkout event generates a SHA-256 checksum incorporating the previous event's hash.

- **Immutability Principle**: Because modifying or deleting an individual event record would break the mathematical integrity of subsequent chain links, core financial event hashes cannot be deleted or rewritten during the retention period.
- **Privacy by Design**: Where data erasure requests (e.g., GDPR Article 17) apply to personal identifiers, AEGIS pseudonyms or purges personal identity fields from operational read tables while preserving mathematical hash-chain continuity for regulatory auditability.

---

## 6. Data Security Measures

AEGIS applies enterprise-grade technical and organizational measures:
- **Encryption in Transit**: All API, web console, and worker communication is enforced over TLS 1.3 / HTTPS.
- **Encryption at Rest**: PostgreSQL databases, local object storage, and audit logs are encrypted at rest using AES-256.
- **Credential Protection**: Passwords hashed with PBKDF2-SHA256 (600,000+ iterations); API keys stored as salted SHA-256 digests; webhook events signed via HMAC-SHA256 (`AEGIS-Signature`).
- **Strict Multi-Tenant Isolation**: Tenant scoping is validated at the database layer and ORM repository layer; cross-tenant access triggers fail-closed security exceptions (`TenantIsolationError`).
- **Principle of Least Privilege**: 6 canonical RBAC roles restrict access to the minimum permissions required for each user and agent.

---

## 7. Data Retention & Deletion

- **Account Data**: Maintained for the duration of Customer's active subscription and deleted within 60 days following account termination, except as required by law.
- **Financial Audit Logs & Hash Chains**: Retained for seven (7) years to comply with statutory accounting, anti-fraud, and tax record-keeping requirements.
- **Temporary Uploads & Previews**: Staged files not committed to dispute cases or evidence graphs are purged within 30 days.

---

## 8. International Data Transfers

When transferring personal data outside the European Economic Area (EEA), the United Kingdom, or Switzerland, AEGIS relies on adequacy decisions or standard contractual clauses (SCCs) approved by the European Commission, combined with technical encryption safeguards.

---

## 9. Your Data Rights

Depending on your jurisdiction (such as under GDPR, UK GDPR, or CCPA/CPRA), you may have the right to:
- Access and obtain a copy of your personal data;
- Request correction of inaccurate personal information;
- Request erasure of personal information (subject to statutory audit exceptions);
- Restrict or object to certain processing activities;
- Data portability in a structured, machine-readable format;
- Withdraw consent at any time without affecting past lawful processing.

To exercise these rights, contact our Privacy Officer at `privacy@aegis-platform.test`.

---

## 10. Contact Information

For inquiries regarding this Privacy Policy or our data protection practices, please contact:

**AEGIS Platform Inc.**  
Attention: Privacy & Compliance Office  
Email: `privacy@aegis-platform.test`  
Security Incident Reporting: `security@aegis-platform.test`
