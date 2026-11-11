# AEGIS Terms of Service

**Effective Date:** November 12, 2026  
**Last Updated:** November 12, 2026  
**Platform:** AEGIS (*Agentic Enforcement, Governance and Investigation System*)

PLEASE READ THESE TERMS OF SERVICE ("TERMS") CAREFULLY. BY CREATING AN ACCOUNT, ACCESSING THE AEGIS CONTROL PLANE, GENERATING API KEYS, OR CONNECTING AUTONOMOUS AGENTS TO THE AEGIS PLATFORM, YOU ("CUSTOMER", "YOU") AGREE TO BE BOUND BY THESE TERMS WITH AEGIS PLATFORM INC. ("COMPANY", "WE", "US"). IF YOU DO NOT AGREE, DO NOT ACCESS OR USE THE SERVICE.

---

## 1. Description of Service

AEGIS provides an algorithmic governance, policy enforcement, forensic replay, and dispute management platform for autonomous software agents and automated purchasing systems. The platform includes:
- **AgentPay Guardian**: Deterministic policy evaluation, Spending Passports, budget allocation, and approval workflows.
- **GhostPay**: Deterministic read-only replay, counterfactual policy simulation, and financial provenance tracking.
- **DisputeOS**: Multi-tenant dispute case management, evidence graphs, contradiction detection, and response drafting.
- **Unified Control Plane & SDKs**: REST APIs (`/v1/*`), worker orchestration, web console, and client SDKs.

---

## 2. Strict Non-Custodial Architecture & Escrow Disclaimer

> [!IMPORTANT]
> **AEGIS IS NOT A BANK, MONEY TRANSMITTER, BROKER, OR CUSTODIAL ESCROW AGENT.**

2.1. **Zero Custody of Funds**: AEGIS never holds, deposits, pools, custodies, or touches Customer fiat currency, merchant funds, or digital assets. AEGIS does not maintain escrow balances, merchant reserve accounts, or payment settlement accounts.

2.2. **Direct Third-Party Processing**: All financial transactions, authorizations, and settlements initiated through or governed by AEGIS are executed directly between Customer (or Customer's merchant accounts) and third-party payment processors (e.g., PayPal, credit card acquirers, or banking institutions). 

2.3. **Algorithmic Gateway Only**: AEGIS operates purely as an algorithmic authorization gateway and cryptographic evidence recorder. AEGIS's transmission of signals, approvals, or tokens does not constitute an assumption of financial liability or a transfer of funds by AEGIS.

---

## 3. Customer Responsibility for Autonomous Agents

3.1. **Agent Autonomy and Risk**: Customer acknowledges that artificial intelligence (AI) agents, large language model (LLM) workflows, and autonomous scripts operate probabilistically. Customer retains sole and absolute responsibility for:
- Configuring appropriate Spending Passports, transaction limits, and velocity caps.
- Selecting allowlisted merchant domains and categories.
- Establishing human-in-the-loop escalation thresholds.
- Monitoring agent logs, spending proposals, and checkout attempts.

3.2. **Liability for Authorized Spends**: Any transaction, commitment, or purchase that passes Customer's configured Spending Passport rules or receives human operator approval is deemed authorized by Customer. Customer is solely liable to merchants, suppliers, and payment processors for all charges incurred by Customer's agents.

3.3. **Deterministic Controls**: Customer agrees never to circumvent, bypass, or instruct agents to evade AEGIS deterministic policy engines or approval gates.

---

## 4. Accounts, Role-Based Access Control (RBAC) & API Key Security

4.1. **Multi-Tenant Identity**: Access to AEGIS requires organization registration. Customer must maintain accurate organization details and authorized administrator contact information.

4.2. **Canonical RBAC Roles**: Customer must enforce the principle of least privilege using AEGIS's 6 canonical roles:
- `OWNER`: Full administrative and organizational authority.
- `ADMIN`: Operational and credential management.
- `OPERATOR`: Spend escalation approvals, passport management, and dispute workflows.
- `AUDITOR`: Read-only compliance and forensic simulation access.
- `AGENT_SERVICE`: Autonomous worker machine credentials (strictly prohibited from human approval authority).
- `VIEWER`: Read-only analytics and audit inspection.

4.3. **Credential Safeguards**: Customer is responsible for safeguarding API keys (`aegis_<env>_...`), JWT tokens, and signing secrets. Any API call authenticated with Customer's API keys will be attributed to Customer. Customer must immediately revoke compromised keys via the AEGIS Console or API.

---

## 5. Acceptable Use Policy (AUP)

Customer shall not, and shall not permit any third party or autonomous agent to:
- Use AEGIS for fraudulent transactions, money laundering, terrorist financing, or sanctions evasion.
- Transact with illegal goods, unlicensed gambling, or unlawful adult services.
- Execute adversarial prompt injection or evasion techniques intended to trick Spending Passports into approving unauthorized transactions.
- Perform denial-of-service, penetration testing, or vulnerability scanning against AEGIS infrastructure without prior written authorization.
- Resell, sublicense, or operate AEGIS as a managed service bureau without a commercial partner agreement.

---

## 6. Evidence Provenance, DisputeOS & Replay Guarantees

6.1. **Cryptographic Proof Chain**: AEGIS maintains an immutable, SHA-256 hash-chained event ledger (`FinancialEvent`) for audit provenance. Customer acknowledges that recorded hashes represent deterministic evidence of authorization decisions at the time of execution.

6.2. **GhostPay Read-Only Replay**: Replays executed within GhostPay operate in an isolated sandbox (`executed_payment = False`) and do not initiate charges or communicate with live payment provider networks.

6.3. **Dispute Submissions**: DisputeOS provides evidence synthesis and recommendation drafting. Customer's human operators are required to review, verify, and seal all dispute filings before submission to payment processors. AEGIS does not guarantee dispute win rates or processor arbitration outcomes.

---

## 7. Intellectual Property & Customer Data

7.1. **AEGIS IP**: Company retains all right, title, and interest in and to the AEGIS platform, codebase, proprietary policy algorithms, documentation, and logos.

7.2. **Customer Data**: Customer retains all rights to Customer data, spending configurations, transaction metadata, and dispute evidence artifacts. Customer grants AEGIS a limited license to process Customer data solely to deliver the services and maintain the audit ledger.

---

## 8. Warranties, Disclaimers & Limitation of Liability

8.1. **Disclaimer of Warranties**: THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS. COMPANY DISCLAIMS ALL WARRANTIES, EXPRESS, IMPLIED, OR STATUTORY, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.

8.2. **Limitation of Liability**: TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT SHALL COMPANY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS, LOSS OF DATA, OR LOSS OF BUSINESS OPPORTUNITY, ARISING OUT OF OR IN CONNECTION WITH AGENT SPENDING, MERCHANT FAILURES, OR PAYMENT PROCESSOR ACTIONS.

8.3. **Liability Cap**: COMPANY'S TOTAL AGGREGATE LIABILITY FOR ALL CLAIMS ARISING OUT OF THESE TERMS SHALL NOT EXCEED THE TOTAL FEES PAID BY CUSTOMER TO COMPANY UNDER THESE TERMS IN THE TWELVE (12) MONTHS PRECEDING THE EVENT GIVING RISE TO LIABILITY.

---

## 9. Indemnification

Customer shall defend, indemnify, and hold harmless Company, its affiliates, and their respective directors, officers, and employees from and against any third-party claims, losses, liabilities, damages, and expenses (including reasonable attorneys' fees) arising out of or related to:
- Actions, contracts, purchases, or debts incurred by Customer's autonomous AI agents;
- Customer's breach of these Terms or the Acceptable Use Policy;
- Disputes between Customer and merchants, payment processors, or cardholders.

---

## 10. Term & Termination

10.1. **Termination for Convenience**: Customer may terminate by closing their organization account and revoking all API keys.

10.2. **Termination for Cause**: Company may suspend or terminate Customer's access immediately if Customer breaches these Terms, fails to pay fees, or engages in activity that threatens platform security or regulatory compliance.

10.3. **Data Retention on Termination**: Upon termination, Customer may export audit logs and evidence records. Hash chains and financial event records are retained in accordance with statutory accounting and compliance requirements.

---

## 11. General Provisions

- **Governing Law**: These Terms are governed by the laws of the State of Delaware, without regard to conflict of law principles.
- **Severability**: If any provision of these Terms is held invalid or unenforceable, the remaining provisions will remain in full force.
- **Entire Agreement**: These Terms, together with the Privacy Policy and Data Processing Addendum, constitute the entire agreement between Customer and Company regarding the subject matter herein.
