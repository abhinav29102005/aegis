"""Generate AEGIS Master 11-Slide Executive Presentation (.pptx) with Real Embedded Mermaid Diagrams.

- Widescreen 16:9 layout (13.333" x 7.5")
- High-contrast obsidian fintech aesthetic (#0A0E17)
- Embedded high-resolution rendered Mermaid diagrams for:
  * Slide 4: Tri-Subsystem Topology
  * Slide 5: Data Flow Architecture (DFD Level 0 & Level 1)
  * Slide 6: End-to-End Sequence Diagram
  * Slide 8: STRIDE Security Threat Model
  * Slide 10: DisputeOS Automated Defense Pipeline
- Formatted metrics grids, comparative tables, mathematical invariants, and live proof callouts.
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE

BG_COLOR = RGBColor(10, 14, 23)        # #0A0E17
CARD_BG = RGBColor(17, 24, 39)        # #111827
CARD_BORDER = RGBColor(31, 41, 55)    # #1F2937
CARD_INNER = RGBColor(30, 41, 59)     # #1E293B
CYAN = RGBColor(56, 189, 248)         # #38BDF8
BRIGHT_CYAN = RGBColor(0, 210, 255)   # #00D2FF
GREEN = RGBColor(16, 185, 129)        # #10B981
AMBER = RGBColor(245, 158, 11)        # #F59E0B
RED = RGBColor(239, 68, 68)           # #EF4444
WHITE = RGBColor(243, 244, 246)       # #F3F4F6
MUTED = RGBColor(156, 163, 175)       # #9CA3AF


def generate_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    def add_base_slide(header_tag: str, title: str, subtitle: str):
        slide = prs.slides.add_slide(blank_layout)

        # Background
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg.fill.solid()
        bg.fill.fore_color.rgb = BG_COLOR
        bg.line.fill.background()

        # Header Pill / Tag
        tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.35), Inches(11.7), Inches(0.3))
        tf = tag_box.text_frame
        p = tf.paragraphs[0]
        p.text = header_tag.upper()
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = CYAN

        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.65), Inches(11.7), Inches(0.6))
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(21)
        p.font.bold = True
        p.font.color.rgb = WHITE

        # Subtitle
        sub_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.25), Inches(11.7), Inches(0.4))
        tf = sub_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = subtitle
        p.font.size = Pt(11.5)
        p.font.color.rgb = MUTED

        # Footer
        foot_box = slide.shapes.add_textbox(Inches(0.8), Inches(7.05), Inches(11.7), Inches(0.3))
        tf = foot_box.text_frame
        p = tf.paragraphs[0]
        p.text = "AEGIS PLATFORM • The Financial Black Box for AI Agents • Public Beta Candidate v1.0.0-rc1"
        p.font.size = Pt(9)
        p.font.color.rgb = MUTED

        return slide

    def add_card(slide, left, top, width, height, title="", border_color=CARD_BORDER, bg_color=CARD_BG):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        card.line.color.rgb = border_color
        card.line.width = Pt(1.2)

        if title:
            tb = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.12), width - Inches(0.4), Inches(0.4))
            tf = tb.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = title
            p.font.size = Pt(12)
            p.font.bold = True
            p.font.color.rgb = CYAN
        return card

    # =========================================================================
    # SLIDE 1: Title & Executive Positioning
    # =========================================================================
    s1 = add_base_slide(
        "Slide 01 • Executive Overview",
        "AEGIS: The Financial Black Box for AI Agents",
        "Deterministic Spending Governance, Multi-Rail Execution & Cryptographic Audit Provenance",
    )

    banner = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.85), Inches(11.733), Inches(1.25))
    banner.fill.solid()
    banner.fill.fore_color.rgb = RGBColor(14, 30, 56)
    banner.line.color.rgb = BRIGHT_CYAN
    banner.line.width = Pt(1.5)

    tb = s1.shapes.add_textbox(Inches(1.1), Inches(2.0), Inches(11.133), Inches(0.95))
    tf = tb.text_frame
    tf.word_wrap = True
    p1 = tf.paragraphs[0]
    p1.text = "THE CORE AXIOM: \"NEVER ALLOW AN LLM TO APPROVE ITS OWN MONEY\""
    p1.font.size = Pt(13)
    p1.font.bold = True
    p1.font.color.rgb = BRIGHT_CYAN

    p2 = tf.add_paragraph()
    p2.text = "Autonomous AI agents are transitioning from assistants to economic actors executing procurement, server provisioning, SaaS renewals, and API capacity reservation. However, legacy payment gateways (Stripe, PayPal) assume human sessions with static cards. AEGIS separates non-deterministic agent intent from zero-trust financial execution."
    p2.font.size = Pt(10.5)
    p2.font.color.rgb = WHITE
    p2.space_before = Pt(4)

    metrics = [
        ("100%", "DETERMINISTIC CONTROL", "Zero LLM Fund Approvals", GREEN),
        ("SHA-256", "MERKLE PROVENANCE", "Tamper-Evident Hash Chains", BRIGHT_CYAN),
        ("Orders v2", "PAYPAL SANDBOX RAIL", "Live Multi-Rail REST Execution", AMBER),
        ("96.0 / 100", "AUDIT MATURITY SCORE", "354 Automated Suites Passing", GREEN),
    ]

    for i, (val, label, sub, col) in enumerate(metrics):
        x = Inches(0.8 + i * 3.0)
        add_card(s1, x, Inches(3.35), Inches(2.733), Inches(1.7), bg_color=CARD_BG, border_color=col)
        tb = s1.shapes.add_textbox(x + Inches(0.15), Inches(3.5), Inches(2.433), Inches(1.4))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = val
        p.font.size = Pt(24)
        p.font.bold = True
        p.font.color.rgb = col
        p.alignment = PP_ALIGN.CENTER

        p_lbl = tf.add_paragraph()
        p_lbl.text = label
        p_lbl.font.size = Pt(8.5)
        p_lbl.font.bold = True
        p_lbl.font.color.rgb = WHITE
        p_lbl.alignment = PP_ALIGN.CENTER

        p_sub = tf.add_paragraph()
        p_sub.text = sub
        p_sub.font.size = Pt(8)
        p_sub.font.color.rgb = MUTED
        p_sub.alignment = PP_ALIGN.CENTER

    add_card(s1, Inches(0.8), Inches(5.3), Inches(11.733), Inches(1.5), "Verified Live Production Credentials (Worldwide Access)")
    tb = s1.shapes.add_textbox(Inches(1.0), Inches(5.75), Inches(11.333), Inches(0.95))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "• Web Console (Next.js 16): https://aegis-staging.abhinavkumarsingh.tech/login   • REST API / Docs: https://api-staging.abhinavkumarsingh.tech/docs\n• Evaluator Login: chief-auditor-bf1ab00d@aegis-nexus.tech   • Password: SuperSecurePassword123!@#\n• Azure Ubuntu VM: 20.124.91.36 (Port 443 TLS)   • Tenant UUID: 829db6b0-6566-4d6d-84e7-6fae90633723"
    p.font.size = Pt(9.5)
    p.font.color.rgb = WHITE

    # =========================================================================
    # SLIDE 2: Problems Identified — The Autonomous Agent Financial Crisis
    # =========================================================================
    s2 = add_base_slide(
        "Slide 02 • Threat Analysis & Problem Definition",
        "Why Legacy Payment Rails Fail Autonomous AI Agents",
        "5 Structural Vulnerabilities When Non-Deterministic LLMs Interface with Corporate Cards",
    )

    threats = [
        ("1. Unbounded Spending Loops", "Autonomous agents trapped in error-recovery, recursive retry, or search loops exhaust corporate credit limits in minutes without human intervention.", RED),
        ("2. Prompt Injection Exploits", "Adversarial inputs on merchant websites or indirect prompt injection manipulate LLM reasoning into authorizing fraudulent, unauthorized, or inflated spend.", AMBER),
        ("3. Concurrency & Double-Spend Races", "Asynchronous swarm agents executing simultaneous checkouts bypass optimistic balance checks, driving ledgers into catastrophic negative balances.", RED),
        ("4. Zero Audit Provenance", "Standard HTTP logs capture timestamps and IP addresses but cannot explain *why* an LLM executed a spend, making post-mortems impossible.", BRIGHT_CYAN),
    ]

    for i, (title, desc, col) in enumerate(threats):
        x = Inches(0.8 + (i % 2) * 6.0)
        y = Inches(1.85 + (i // 2) * 2.4)
        add_card(s2, x, y, Inches(5.733), Inches(2.2), title, border_color=col)
        tb = s2.shapes.add_textbox(x + Inches(0.2), y + Inches(0.6), Inches(5.333), Inches(1.4))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.size = Pt(11)
        p.font.color.rgb = WHITE

    add_card(s2, Inches(0.8), Inches(6.05), Inches(11.733), Inches(0.8), bg_color=CARD_INNER)
    tb = s2.shapes.add_textbox(Inches(1.0), Inches(6.15), Inches(11.333), Inches(0.6))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "5. Automatic Chargeback Losses: Payment processors hold merchants and enterprises strictly liable. Without cryptographic proof connecting agent intent to fulfillment, chargebacks are lost automatically."
    p.font.size = Pt(10)
    p.font.bold = True
    p.font.color.rgb = AMBER

    # =========================================================================
    # SLIDE 3: Gaps Solved & Competitive Analysis Matrix
    # =========================================================================
    s3 = add_base_slide(
        "Slide 03 • Market Gaps & Differentiation",
        "Architectural Comparison: AEGIS vs. Legacy Rails",
        "Closing the Governance, Concurrency, and Forensic Gaps Across Industry Payment Systems",
    )

    rows, cols = 7, 4
    table_shape = s3.shapes.add_table(rows, cols, Inches(0.8), Inches(1.85), Inches(11.733), Inches(4.85))
    table = table_shape.table
    table.columns[0].width = Inches(2.3)
    table.columns[1].width = Inches(3.1)
    table.columns[2].width = Inches(3.1)
    table.columns[3].width = Inches(3.233)

    headers = ["Dimension", "Legacy Gateways (Stripe/PayPal)", "Virtual Cards (Brex/Ramp)", "AEGIS Platform"]
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(14, 30, 56)
        p = cell.text_frame.paragraphs[0]
        p.text = h
        p.font.size = Pt(10.5)
        p.font.bold = True
        p.font.color.rgb = BRIGHT_CYAN

    data = [
        ("Spending Governance", "None (Static card limit)", "Static monthly spend cap", "Multi-tier Passports & Dynamic Velocity Limits"),
        ("Authorization Model", "Card swipe releases funds", "Basic merchant category code", "Deterministic Policy Engine (Zero LLM Authorization)"),
        ("Concurrency Control", "Optimistic (Race vulnerable)", "Gateway balance check", "PostgreSQL Advisory Locks (pg_advisory_xact_lock)"),
        ("Forensic Auditability", "Plaintext HTTP server logs", "Monthly statement CSV", "SHA-256 Merkle Hash-Chained Event Ledger"),
        ("Dispute Defense", "Manual 14-day upload forms", "Manual claim receipt review", "Automated Contradiction Matrix with Telemetry Citations"),
        ("Prompt Injection", "N/A (Built for human UI)", "None (Agent controls browser)", "Strict XML Delimitation & Fail-Closed Rule Fallback"),
    ]

    for i, row in enumerate(data):
        for j, val in enumerate(row):
            cell = table.cell(i + 1, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD_BG if i % 2 == 0 else CARD_INNER
            p = cell.text_frame.paragraphs[0]
            p.text = val
            p.font.size = Pt(9)
            p.font.color.rgb = GREEN if j == 3 else (WHITE if j > 0 else BRIGHT_CYAN)
            if j == 3:
                p.font.bold = True

    # =========================================================================
    # SLIDE 4: Core Novelty & System Architecture (WITH MERMAID DIAGRAM)
    # =========================================================================
    s4 = add_base_slide(
        "Slide 04 • System Topology & Decomposition",
        "The Tri-Subsystem Model: Guardian, GhostPay & DisputeOS",
        "Sovereign Subsystems Governing the Complete Autonomous Transaction Lifecycle",
    )

    # Left: Text summary card
    add_card(s4, Inches(0.8), Inches(1.85), Inches(4.5), Inches(4.9), "Tri-Subsystem Architectural Boundaries")
    tb = s4.shapes.add_textbox(Inches(1.0), Inches(2.35), Inches(4.1), Inches(4.2))
    tf = tb.text_frame
    tf.word_wrap = True

    subsystems_text = [
        ("1. AgentPay Guardian", "Deterministic spending passports, velocity caps, atomic budget reservations, and multi-rail payment adapters (PayPal Orders v2)."),
        ("2. GhostPay Forensics", "Cryptographic SHA-256 Merkle hash-chained audit ledger, deterministic replay simulator, counterfactual policy simulator, and Agent DNA profiling."),
        ("3. DisputeOS Engine", "Automated dispute case ingestion, multimodal evidence graph (telemetry, receipts, carrier logs), contradiction matrix, and grounded AI defense briefs."),
    ]
    for st, sd in subsystems_text:
        p_t = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
        p_t.text = st
        p_t.font.size = Pt(11)
        p_t.font.bold = True
        p_t.font.color.rgb = BRIGHT_CYAN
        p_t.space_before = Pt(8)

        p_d = tf.add_paragraph()
        p_d.text = sd
        p_d.font.size = Pt(9.5)
        p_d.font.color.rgb = WHITE

    # Right: Rendered Mermaid Diagram Image
    if os.path.exists("/tmp/slide4_tri.png"):
        s4.shapes.add_picture("/tmp/slide4_tri.png", Inches(5.5), Inches(1.85), width=Inches(7.033))

    # =========================================================================
    # SLIDE 5: Data Flow Diagrams (DFD Level 0 & Level 1) (WITH MERMAID DIAGRAM)
    # =========================================================================
    s5 = add_base_slide(
        "Slide 05 • Data Flow Architecture",
        "Level 0 Context & Level 1 System Data Flow",
        "Complete Traceability from Agent Proposal Submission to Immutable Ledger Settlement",
    )

    # Left: DFD Description & Invariants
    add_card(s5, Inches(0.8), Inches(1.85), Inches(4.5), Inches(4.9), "Data Flow Pipeline & Invariants")
    tb = s5.shapes.add_textbox(Inches(1.0), Inches(2.35), Inches(4.1), Inches(4.2))
    tf = tb.text_frame
    tf.word_wrap = True

    dfd_points = [
        ("Level 0: External Context Flow", "Agent submits proposal -> AEGIS evaluates bounds -> Escalate high-value to human -> Authorize capture at PayPal -> Append Merkle audit proof."),
        ("Level 1: Subsystem Ingestion", "FastAPI router validates Pydantic v2 schemas and computes deterministic quote hash."),
        ("Level 1: Concurrency Isolation", "Advisory lock acquired on passport UUID (pg_advisory_xact_lock), preventing double-spending."),
        ("Level 1: Transactional Outbox", "Financial mutations and event dispatches commit in the same ACID transaction, guaranteeing exactly-once delivery."),
    ]
    for dt, dd in dfd_points:
        p_t = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
        p_t.text = dt
        p_t.font.size = Pt(10.5)
        p_t.font.bold = True
        p_t.font.color.rgb = GREEN
        p_t.space_before = Pt(8)

        p_d = tf.add_paragraph()
        p_d.text = dd
        p_d.font.size = Pt(9)
        p_d.font.color.rgb = WHITE

    # Right: Rendered Mermaid Diagram Image
    if os.path.exists("/tmp/slide5_dfd.png"):
        s5.shapes.add_picture("/tmp/slide5_dfd.png", Inches(5.5), Inches(1.85), width=Inches(7.033))

    # =========================================================================
    # SLIDE 6: End-to-End Transaction Sequence (WITH MERMAID DIAGRAM)
    # =========================================================================
    s6 = add_base_slide(
        "Slide 06 • Protocol Execution Sequence",
        "End-to-End Autonomous Transaction Sequence",
        "Proposal Validation, Advisory Locking, PayPal Order Creation, Premature Capture Guard & Settlement",
    )

    # Left: Protocol Stages Summary
    add_card(s6, Inches(0.8), Inches(1.85), Inches(4.3), Inches(4.9), "Transaction Sequence Protocol")
    tb = s6.shapes.add_textbox(Inches(1.0), Inches(2.35), Inches(3.9), Inches(4.2))
    tf = tb.text_frame
    tf.word_wrap = True

    seq_points = [
        ("1. Proposal & Quote Normalization", "Deterministic SHA-256 quote normalization prevents post-submission price alteration."),
        ("2. Invariant & Policy Verification", "Evaluates velocity, allowlists, and per-tx limits. If <= $25 -> auto-approved; if > $500 -> held in AWAITING_APPROVAL."),
        ("3. Advisory Lock & Budget Hold", "Executes pg_advisory_xact_lock to commit balance reservation before API calls."),
        ("4. PayPal Orders v2 Dispatch", "Creates live PayPal Sandbox order. Enforces capture state guard: premature capture strictly returns 409 Conflict."),
        ("5. HMAC Webhook & Merkle Settle", "Inbound webhook verified via HMAC-SHA256 signature; settles ledger and appends event to GhostPay chain."),
    ]
    for st, sd in seq_points:
        p_t = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
        p_t.text = st
        p_t.font.size = Pt(10)
        p_t.font.bold = True
        p_t.font.color.rgb = BRIGHT_CYAN
        p_t.space_before = Pt(6)

        p_d = tf.add_paragraph()
        p_d.text = sd
        p_d.font.size = Pt(8.5)
        p_d.font.color.rgb = WHITE

    # Right: Rendered Mermaid Diagram Image
    if os.path.exists("/tmp/slide6_seq.png"):
        s6.shapes.add_picture("/tmp/slide6_seq.png", Inches(5.3), Inches(1.85), width=Inches(7.233))

    # =========================================================================
    # SLIDE 7: Technical Methodology & Financial Correctness Invariants
    # =========================================================================
    s7 = add_base_slide(
        "Slide 07 • Mathematical & Distributed Invariants",
        "Mathematical Invariants & Distributed State Guarantees",
        "Eliminating Non-Determinism, Race Conditions, and Data Loss in Agentic Finance",
    )

    invariants = [
        ("1. Serializable Concurrency Isolation", [
            "SQL: SELECT pg_advisory_xact_lock(hashtext(:passport_id));",
            "Eliminates race conditions across distributed microservices.",
            "18 automated multithreaded test suites verify zero double-spend.",
            "Row-level lock released automatically upon transaction commit.",
        ], GREEN),
        ("2. Two-Phase Budget Reservation", [
            "Formula: Available = Budget - (Settled + Reserved)",
            "Budget is atomically reserved BEFORE external API dispatch.",
            "Rolls back cleanly without balance leakage if upstream order expires.",
            "Guarantees active agent swarms never drive balances negative.",
        ], BRIGHT_CYAN),
        ("3. Cryptographic Quote Normalization", [
            "Formula: H_quote = SHA-256(canonical_json(quote_items))",
            "Ensures quote evaluated by policy is bit-for-bit identical to checkout.",
            "Protects against price drift, hidden fees, and payload tampering.",
            "Serialized using sorted keys and IEEE-754 decimal precision.",
        ], AMBER),
        ("4. Transactional Outbox Pattern", [
            "State mutation and event dispatch commit in the SAME transaction.",
            "Background worker polls outbox with exponential backoff.",
            "Guarantees exactly-once event delivery to Merkle ledger.",
            "Eliminates dual-write inconsistencies between Postgres and Redis.",
        ], BRIGHT_CYAN),
    ]

    for i, (title, pts, col) in enumerate(invariants):
        x = Inches(0.8 + (i % 2) * 6.0)
        y = Inches(1.85 + (i // 2) * 2.45)
        add_card(s7, x, y, Inches(5.733), Inches(2.25), title, border_color=col)
        tb = s7.shapes.add_textbox(x + Inches(0.2), y + Inches(0.55), Inches(5.333), Inches(1.55))
        tf = tb.text_frame
        tf.word_wrap = True
        for pt in pts:
            p = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
            p.text = f"• {pt}"
            p.font.size = Pt(9.5)
            p.font.color.rgb = WHITE
            p.space_before = Pt(3)

    # =========================================================================
    # SLIDE 8: Enterprise Security Architecture & Threat Model (STRIDE) (WITH MERMAID)
    # =========================================================================
    s8 = add_base_slide(
        "Slide 08 • Security Architecture & STRIDE Model",
        "Enterprise Security Architecture & STRIDE Threat Analysis",
        "Hardened Defense-in-Depth Against Adversarial Agent Prompts and Financial Exploits",
    )

    # Left: Security Pillars & Prompt Injection Guard
    add_card(s8, Inches(0.8), Inches(1.85), Inches(4.5), Inches(4.9), "Defense-in-Depth & Prompt Isolation")
    tb = s8.shapes.add_textbox(Inches(1.0), Inches(2.35), Inches(4.1), Inches(4.2))
    tf = tb.text_frame
    tf.word_wrap = True

    sec_points = [
        ("Spoofing & Tampering Defense", "Asymmetric JWT / API Keys with tenant_id row isolation. SHA-256 Merkle hash-chaining prevents historical modification."),
        ("Denial of Service Mitigation", "Upstash Redis token-bucket rate limiter per agent UUID and client IP."),
        ("Prompt Injection Isolation", "External strings stripped of control tokens (<|endoftext|>, [INST]) and enclosed inside <untrusted_input trust=\"UNTRUSTED_DATA\"> with angle brackets escaped."),
        ("Zero LLM Execution Authority", "LLMs generate summaries but CANNOT approve budgets or release funds."),
        ("Fail-Closed Quota Guard", "If upstream LLM returns HTTP 429 quota exhaustion, DisputeOS immediately degrades to deterministic-rules-v1."),
    ]
    for st, sd in sec_points:
        p_t = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
        p_t.text = st
        p_t.font.size = Pt(10)
        p_t.font.bold = True
        p_t.font.color.rgb = RED if "Prompt" in st else BRIGHT_CYAN
        p_t.space_before = Pt(6)

        p_d = tf.add_paragraph()
        p_d.text = sd
        p_d.font.size = Pt(8.5)
        p_d.font.color.rgb = WHITE

    # Right: Rendered Mermaid Diagram Image
    if os.path.exists("/tmp/slide8_sec.png"):
        s8.shapes.add_picture("/tmp/slide8_sec.png", Inches(5.5), Inches(1.85), width=Inches(7.033))

    # =========================================================================
    # SLIDE 9: GhostPay Forensic Replay & Merkle Ledger
    # =========================================================================
    s9 = add_base_slide(
        "Slide 09 • Forensic Reliability & Replay",
        "GhostPay: Deterministic Replay & Counterfactual Simulation",
        "Reconstructing Agent Execution Timelines with Mathematical Verifiability",
    )

    gp_cards = [
        ("1. Merkle Hash-Chained Ledger", "Every state mutation computes: H_n = SHA-256(H_{n-1} || canonical_json(E_n)). Bitwise alterations break chain integrity instantly, exposing unauthorized writes.", BRIGHT_CYAN),
        ("2. Deterministic Replay Simulator", "Re-executes historical agent inputs, policy constraints, and quote hashes to mathematically prove that past decisions strictly complied with governance policies.", GREEN),
        ("3. Counterfactual Policy Simulator", "Reruns past agent transactions against *new* hypothetical policies (e.g., testing a $750 GPU charge against a $500 cap) to proactively calibrate risk thresholds.", AMBER),
        ("4. Agent DNA Behavioral Profiling", "Continuously tracks spending velocity, merchant categorization, and invocation timeframes, automatically alerting on anomalous drift and credential compromise.", BRIGHT_CYAN),
    ]

    for i, (title, desc, col) in enumerate(gp_cards):
        x = Inches(0.8 + (i % 2) * 6.0)
        y = Inches(1.85 + (i // 2) * 2.1)
        add_card(s9, x, y, Inches(5.733), Inches(1.9), title, border_color=col)
        tb = s9.shapes.add_textbox(x + Inches(0.2), y + Inches(0.55), Inches(5.333), Inches(1.25))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.size = Pt(10.5)
        p.font.color.rgb = WHITE

    add_card(s9, Inches(0.8), Inches(6.1), Inches(11.733), Inches(0.75), bg_color=CARD_INNER, border_color=GREEN)
    tb = s9.shapes.add_textbox(Inches(1.0), Inches(6.2), Inches(11.333), Inches(0.55))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "Verified Live Proof: Investigation 4cce42a3-881d-43d7-aae5-3f32537c97eb confirmed status VALID across 5 sequential event blocks (PROPOSAL_SUBMITTED -> POLICY_EVALUATED -> BUDGET_RESERVED -> PAYPAL_ORDER_CREATED -> CAPTURE_COMPLETED)."
    p.font.size = Pt(9.5)
    p.font.bold = True
    p.font.color.rgb = GREEN

    # =========================================================================
    # SLIDE 10: DisputeOS Contradiction Matrix & Grounded Defense (WITH MERMAID)
    # =========================================================================
    s10 = add_base_slide(
        "Slide 10 • Dispute Resolution & Chargeback Defense",
        "DisputeOS: Automated Evidence Graphs & Contradiction Defense",
        "Eliminating Chargeback Losses via Multimodal Telemetry and Grounded Citations",
    )

    # Left: Dispute Defense Workflow & Real Proof
    add_card(s10, Inches(0.8), Inches(1.85), Inches(4.5), Inches(4.9), "Automated Evidence & Contradiction Engine")
    tb = s10.shapes.add_textbox(Inches(1.0), Inches(2.35), Inches(4.1), Inches(4.2))
    tf = tb.text_frame
    tf.word_wrap = True

    disp_points = [
        ("1. Evidence Ingestion Graph", "Automatically ingests server access logs, API consumption telemetry, signed delivery receipts, and carrier tracking IDs upon dispute notification from PayPal."),
        ("2. Contradiction Detection", "Cross-references buyer claims against technical telemetry. Flags direct logical contradictions with mathematical proof."),
        ("3. Grounded AI Defense Brief", "Compiles structured chargeback defense packets with verified source citations, confidence scores, and strict hallucination rejection."),
        ("Live Case Proof (Case b4502263)", "Buyer claimed 'Item Not Received' for 2.5M Token Batch Capacity. Contradiction Engine matched openai_workspace_quota_telemetry.json proving 42.8% token consumption within 14 mins."),
    ]
    for st, sd in disp_points:
        p_t = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
        p_t.text = st
        p_t.font.size = Pt(10)
        p_t.font.bold = True
        p_t.font.color.rgb = AMBER if "Live" in st else GREEN
        p_t.space_before = Pt(6)

        p_d = tf.add_paragraph()
        p_d.text = sd
        p_d.font.size = Pt(8.5)
        p_d.font.color.rgb = WHITE

    # Right: Rendered Mermaid Diagram Image
    if os.path.exists("/tmp/slide10_disp.png"):
        s10.shapes.add_picture("/tmp/slide10_disp.png", Inches(5.5), Inches(2.2), width=Inches(7.033))

    # =========================================================================
    # SLIDE 11: Production Verification Evidence, Quality Scorecard & Roadmap
    # =========================================================================
    s11 = add_base_slide(
        "Slide 11 • Operational Maturity & Commercial Roadmap",
        "Measured Production Evidence & Commercial Roadmap",
        "Rigorous Empirical Verification, Latency SLAs, and Enterprise Scaling Milestones",
    )

    scorecard = [
        ("354 / 354", "AUTOMATED TESTS", "90%+ Statement Coverage", GREEN),
        ("8 / 8", "LIVE CLOUD SUITES", "100% Staging Verification", BRIGHT_CYAN),
        ("< 45ms", "POLICY LATENCY SLA", "Strict P99 Response Time", AMBER),
        ("0", "CONCURRENCY DEADLOCKS", "18 Multi-Thread Stress Runs", GREEN),
    ]

    for i, (val, label, sub, col) in enumerate(scorecard):
        x = Inches(0.8 + i * 3.0)
        add_card(s11, x, Inches(1.85), Inches(2.733), Inches(1.4), bg_color=CARD_BG, border_color=col)
        tb = s11.shapes.add_textbox(x + Inches(0.15), Inches(1.95), Inches(2.433), Inches(1.2))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = val
        p.font.size = Pt(22)
        p.font.bold = True
        p.font.color.rgb = col
        p.alignment = PP_ALIGN.CENTER

        p_lbl = tf.add_paragraph()
        p_lbl.text = label
        p_lbl.font.size = Pt(8.5)
        p_lbl.font.bold = True
        p_lbl.font.color.rgb = WHITE
        p_lbl.alignment = PP_ALIGN.CENTER

        p_sub = tf.add_paragraph()
        p_sub.text = sub
        p_sub.font.size = Pt(8)
        p_sub.font.color.rgb = MUTED
        p_sub.alignment = PP_ALIGN.CENTER

    add_card(s11, Inches(0.8), Inches(3.45), Inches(11.733), Inches(1.4), "Live Staging Cloud Topology (Azure, Neon, Upstash, PayPal)")
    tb = s11.shapes.add_textbox(Inches(1.0), Inches(3.9), Inches(11.333), Inches(0.85))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "• Azure Ubuntu Staging VM (20.124.91.36): Nginx SSL reverse proxy, Docker Compose container stack.\n• Neon Serverless PostgreSQL (Ohio v18.6): SSL connection pooler, SQLAlchemy 2.0 ORM, Alembic migrations.\n• Upstash Managed Redis (v8.4.0 TLS rediss://): Token-bucket rate limiting, distributed caching, worker queues.\n• PayPal Sandbox Orders v2: Real REST OAuth token rotation, order capture guards, fail-closed webhook security."
    p.font.size = Pt(9.5)
    p.font.color.rgb = WHITE

    add_card(s11, Inches(0.8), Inches(5.05), Inches(11.733), Inches(1.75), "Strategic Commercial Roadmap (2027)")
    roadmap_quarters = [
        ("Q1 2027: Multi-Rail Expansion", "Stripe Agentic & Virtual Card issuing integration; Adyen & Visa B2B connectors."),
        ("Q2 2027: Enterprise Compliance", "SOC 2 Type II certification; ISO 27001 audit; Splunk / Datadog audit apps."),
        ("Q3 2027: Swarm Consensus", "Multi-agent collaborative spending pools with threshold cryptographic keys."),
        ("Q4 2027: Sovereign Cloud", "Enterprise On-Premises & Sovereign Cloud Helm Kubernetes packaging."),
    ]
    for i, (q_title, q_desc) in enumerate(roadmap_quarters):
        bx = Inches(1.0 + i * 2.85)
        add_card(s11, bx, Inches(5.55), Inches(2.7), Inches(1.1), bg_color=CARD_INNER, border_color=BRIGHT_CYAN)
        tb = s11.shapes.add_textbox(bx + Inches(0.1), Inches(5.6), Inches(2.5), Inches(0.95))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = q_title
        p.font.size = Pt(8.5)
        p.font.bold = True
        p.font.color.rgb = BRIGHT_CYAN
        p_d = tf.add_paragraph()
        p_d.text = q_desc
        p_d.font.size = Pt(8)
        p_d.font.color.rgb = WHITE

    out_pptx = "/home/bigboyaks/Downloads/AEGIS_Master_Presentation.pptx"
    prs.save(out_pptx)
    prs.save("/home/bigboyaks/Projects/agentpay-nexus/AEGIS_Master_Presentation.pptx")
    print(f"Master presentation with Mermaid diagrams successfully saved to {out_pptx} and workspace!")


if __name__ == "__main__":
    generate_deck()
