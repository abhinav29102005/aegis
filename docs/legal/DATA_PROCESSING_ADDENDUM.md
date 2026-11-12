# Data Processing Addendum (DPA)

**Effective Date:** November 12, 2026  
**Applicability:** Incorporated into and forms part of the AEGIS Terms of Service between AEGIS Platform Inc. ("Processor", "we", "us") and Customer ("Controller", "you").

This Data Processing Addendum ("DPA") governs the processing of Personal Data by Processor in connection with providing the AEGIS platform, pursuant to the European Union General Data Protection Regulation (Regulation (EU) 2016/679) ("GDPR"), UK GDPR, and the California Consumer Privacy Act ("CCPA/CPRA").

---

## 1. Definitions

1.1. **"Applicable Data Protection Law"** means all worldwide privacy and data protection legislation applicable to the personal data processed under the Agreement, including the GDPR, the UK Data Protection Act 2018, and the CCPA/CPRA.

1.2. **"Customer Personal Data"** means any personal data processed by Processor on behalf of Controller in the course of providing the Services.

1.3. **"Sub-processor"** means any third party appointed by or on behalf of Processor to process Customer Personal Data.

1.4. The terms **"Controller"**, **"Processor"**, **"Data Subject"**, **"Personal Data"**, **"Personal Data Breach"**, and **"Processing"** shall have the meanings ascribed to them in the GDPR.

---

## 2. Roles & Scope of Processing

2.1. **Role of the Parties**: The parties acknowledge and agree that with respect to Customer Personal Data, Controller is the Data Controller (or a Processor acting on behalf of a third-party Controller), and AEGIS is the Data Processor.

2.2. **Instructions**: Processor shall process Customer Personal Data exclusively on documented instructions from Controller (including with respect to transfers of personal data), unless required to do so by applicable Union or Member State law. The Terms of Service, this DPA, and Controller's configuration of the Services constitute Controller's complete documented instructions.

2.3. **Scope and Details**: The details of the processing operations (subject matter, duration, nature and purpose of processing, categories of data subjects, and types of personal data) are set forth in **Annex I** of this DPA.

---

## 3. Confidentiality & Personnel

3.1. Processor shall ensure that all personnel authorized to process Customer Personal Data have committed themselves to confidentiality or are under an appropriate statutory obligation of confidentiality.

3.2. Processor shall take commercially reasonable steps to ensure the reliability of any personnel who have access to Customer Personal Data, limiting access to those individuals who require access to perform their employment duties.

---

## 4. Technical and Organizational Security Measures (TOMs)

4.1. Processor shall implement and maintain appropriate technical and organizational measures designed to protect Customer Personal Data against accidental or unlawful destruction, loss, alteration, unauthorized disclosure, or unauthorized access.

4.2. Such measures shall include, at a minimum, the security safeguards detailed in **Annex II** (including TLS 1.3 encryption in transit, AES-256 encryption at rest, PBKDF2-SHA256 password hashing, strict multi-tenant schema isolation, and SHA-256 event hash chains).

---

## 5. Sub-processing

5.1. **Authorized Sub-processors**: Controller grants general written authorization to Processor to engage Sub-processors to perform specific processing activities (e.g., cloud infrastructure and hosting).

5.2. **Sub-processor Obligations**: Processor shall enter into a written agreement with each Sub-processor that imposes data protection obligations no less protective than those imposed on Processor under this DPA. Processor remains fully liable to Controller for the performance of each Sub-processor's obligations.

5.3. **Notice of Changes**: Processor shall maintain an up-to-date list of Sub-processors. Processor shall notify Controller of any intended appointment of a new Sub-processor at least fourteen (14) days prior to authorizing such Sub-processor to process Customer Personal Data, providing Controller the opportunity to object on reasonable data protection grounds.

---

## 6. Data Subject Rights & Regulatory Assistance

6.1. **Assistance with Requests**: Taking into account the nature of the processing, Processor shall assist Controller by appropriate technical and organizational measures, insofar as this is possible, for the fulfilment of Controller's obligation to respond to requests by Data Subjects exercising their statutory rights under Applicable Data Protection Law.

6.2. **Direct Requests**: If a Data Subject submits a request directly to Processor, Processor shall promptly notify Controller and advise the Data Subject to submit their request directly to Controller.

6.3. **DPIA and Prior Consultation**: Processor shall provide reasonable assistance to Controller with any data protection impact assessments (DPIAs) and prior consultations with competent supervisory authorities required under Articles 35 and 36 of the GDPR.

---

## 7. Personal Data Breach Notification

7.1. **Notification Window**: Processor shall notify Controller without undue delay, and in any event within **forty-eight (48) hours**, after becoming aware of a confirmed Personal Data Breach impacting Customer Personal Data.

7.2. **Content of Notification**: The notification shall describe:
- The nature of the breach, including categories and approximate numbers of data subjects and records affected;
- The name and contact details of Processor's Data Protection Officer or security lead;
- The likely consequences of the breach;
- The measures taken or proposed to be taken to mitigate its possible adverse effects.

---

## 8. Audits & Demonstrating Compliance

8.1. Processor shall make available to Controller all information reasonably necessary to demonstrate compliance with the obligations laid down in Article 28 of the GDPR.

8.2. Processor shall allow for and contribute to audits, including inspections, conducted by Controller or an independent auditor mandated by Controller, subject to reasonable advance notice, standard confidentiality commitments, and non-interference with ongoing operations.

---

## 9. Deletion and Return of Personal Data

9.1. Upon termination or expiration of the Agreement, Processor shall, at Controller's election, securely delete or return all Customer Personal Data, and delete existing copies, unless applicable Union, Member State, or national law requires continued storage of the Customer Personal Data.

9.2. **Statutory Audit Exception**: Controller acknowledges that cryptographic financial hash chains (`FinancialEvent`) and records required for statutory accounting, tax, or anti-fraud compliance are maintained in an immutable, pseudonymized state in accordance with statutory retention schedules.

---

## 10. International Transfers & Standard Contractual Clauses

10.1. To the extent processing involves a transfer of Customer Personal Data from the EEA or UK to a country not recognized as providing an adequate level of data protection, the Standard Contractual Clauses (Commission Implementing Decision (EU) 2021/914, Module Two: Controller-to-Processor) are hereby incorporated by reference.

---

## Annex I: Details of Processing

1. **Categories of Data Subjects**:
   - Customer's authorized users, system administrators, and finance operators.
   - Individuals whose purchase proposals, orders, delivery addresses, or dispute artifacts are processed through autonomous agent workflows.
2. **Categories of Personal Data**:
   - Identity data: Name, email address, role, login credentials (hashed).
   - Transaction metadata: Agent ID, purchase proposal summary, order line items, amounts, merchant references, and correlation IDs.
   - Dispute evidence: Invoices, shipping receipts, carrier tracking details, and support communications.
3. **Special Categories of Data (Sensitive Data)**: None intentionally processed. Controller is instructed never to submit sensitive health, biometric, or special category data.
4. **Nature and Purpose of Processing**: Providing autonomous agent spending governance, deterministic policy checks, audit hash chains, GhostPay forensic replay, and DisputeOS evidence management.
5. **Duration of Processing**: For the term of the Agreement, plus applicable statutory retention periods.

---

## Annex II: Technical and Organizational Measures (TOMs)

1. **Access Control & RBAC**: Strict multi-tenant schema isolation, password hashing with PBKDF2-SHA256, salted SHA-256 API key authentication, and 6 canonical RBAC roles (`OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`).
2. **Encryption**: Enforced TLS 1.3 encryption in transit for all web and API endpoints. AES-256 encryption at rest for databases and artifact storage.
3. **Data Integrity & Immutability**: SHA-256 hash chaining of all ledger financial events. Webhook message signing using HMAC-SHA256 (`AEGIS-Signature: t=...,v1=...`).
4. **Disaster Recovery & Business Continuity**: Automated PostgreSQL WAL archiving, Point-In-Time Recovery (PITR) procedures, and redundant container orchestration.
5. **Vulnerability Management**: Continuous dependency scanning, static code analysis (Ruff, ESLint, TypeScript), and pre-commit secret scanning.
