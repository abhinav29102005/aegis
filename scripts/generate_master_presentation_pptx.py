"""Generate AEGIS Master 11-Slide Executive & Technical PowerPoint Presentation (.pptx).

Built with python-pptx:
- Widescreen 16:9 layout (13.333" x 7.5")
- Premium obsidian dark fintech theme (#0A0E17)
- Electric cyan (#00D2FF / #38BDF8), emerald green (#10B981), and slate cards (#111827 / #1E293B)
- Full mathematical formulas, STRIDE threat models, DFD architectures, and real evidence.
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE

# Theme Colors
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
DARK_TEXT = RGBColor(15, 23, 42)


def create_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    def add_base_slide(header_tag: str, title: str, subtitle: str):
        slide = prs.slides.add_slide(blank_layout)

        # Slide Background
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg.fill.solid()
        bg.fill.fore_color.rgb = BG_COLOR
        bg.line.fill.background()

        # Top Category Tag
        tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(0.3))
        tf = tag_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = header_tag.upper()
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = CYAN

        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(11.7), Inches(0.6))
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(22)
        p.font.bold = True
        p.font.color.rgb = WHITE

        # Subtitle
        sub_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.3), Inches(11.7), Inches(0.4))
        tf = sub_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = subtitle
        p.font.size = Pt(12)
        p.font.color.rgb = MUTED

        # Bottom Footer
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
            tb = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.15), width - Inches(0.4), Inches(0.4))
            tf = tb.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = title
            p.font.size = Pt(13)
            p.font.bold = True
            p.font.color.rgb = CYAN
        return card

    # =========================================================================
    # SLIDE 1: Title & Executive Positioning
    # =========================================================================
    s1 = add_base_slide(
        "Slide 01 • Executive Overview",
        "AEGIS: The Financial Black Box for AI Agents",
        "Deterministic Spending Governance, Multi-Rail Execution & Cryptographic Forensic Provenance",
    )

    # Hero Banner
    banner = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.9), Inches(11.733), Inches(1.2))
    banner.fill.solid()
    banner.fill.fore_color.rgb = RGBColor(14, 30, 56)
    banner.line.color.rgb = BRIGHT_CYAN
    banner.line.width = Pt(1.5)

    tb = s1.shapes.add_textbox(Inches(1.1), Inches(2.05), Inches(11.133), Inches(0.9))
    tf = tb.text_frame
    tf.word_wrap = True
    p1 = tf.paragraphs[0]
    p1.text = "THE CORE AXIOM: \"NEVER ALLOW AN LLM TO APPROVE ITS OWN MONEY\""
    p1.font.size = Pt(14)
    p1.font.bold = True
    p1.font.color.rgb = BRIGHT_CYAN

    p2 = tf.add_paragraph()
    p2.text = "Autonomous agents represent trillions in impending economic activity, but legacy payment gateways were built exclusively for human sessions with static cards. AEGIS provides deterministic governance, serializable advisory locks, Merkle hash chains, and automated dispute defense."
    p2.font.size = Pt(11)
    p2.font.color.rgb = WHITE

    # 4 Metric Hero Boxes
    metrics = [
        ("100%", "DETERMINISTIC CONTROL", "Zero LLM Fund Authorizations", GREEN),
        ("SHA-256", "MERKLE PROVENANCE", "Tamper-Evident Hash Chains", BRIGHT_CYAN),
        ("Orders v2", "PAYPAL SANDBOX RAIL", "Live Multi-Rail REST Execution", AMBER),
        ("96.0 / 100", "AUDIT MATURITY SCORE", "354 Automated Suites Passing", GREEN),
    ]

    for i, (val, label, sub, col) in enumerate(metrics):
        x = Inches(0.8 + i * 3.0)
        c = add_card(s1, x, Inches(3.4), Inches(2.733), Inches(1.7), bg_color=CARD_BG, border_color=col)
        tb = s1.shapes.add_textbox(x + Inches(0.15), Inches(3.55), Inches(2.433), Inches(1.4))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = val
        p.font.size = Pt(26)
        p.font.bold = True
        p.font.color.rgb = col
        p.alignment = PP_ALIGN.CENTER

        p_lbl = tf.add_paragraph()
        p_lbl.text = label
        p_lbl.font.size = Pt(9)
        p_lbl.font.bold = True
        p_lbl.font.color.rgb = WHITE
        p_lbl.alignment = PP_ALIGN.CENTER

        p_sub = tf.add_paragraph()
        p_sub.text = sub
        p_sub.font.size = Pt(8.5)
        p_sub.font.color.rgb = MUTED
        p_sub.alignment = PP_ALIGN.CENTER

    # Live Production Credentials Card
    add_card(s1, Inches(0.8), Inches(5.35), Inches(11.733), Inches(1.4), "Verified Live Production Credentials (Worldwide Access)")
    tb = s1.shapes.add_textbox(Inches(1.0), Inches(5.8), Inches(11.333), Inches(0.8))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "• Web Console: https://aegis-staging.abhinavkumarsingh.tech/login   • REST API / Docs: https://api-staging.abhinavkumarsingh.tech/docs\n• Evaluator Login: chief-auditor-bf1ab00d@aegis-nexus.tech   • Password: SuperSecurePassword123!@#\n• Azure Ubuntu VM: 20.124.91.36 (Port 443 TLS)   • Tenant UUID: 829db6b0-6566-4d6d-84e7-6fae90633723"
    p.font.size = Pt(10)
    p.font.color.rgb = WHITE

    # =========================================================================
    # SLIDE 2: The Autonomous Agent Financial Crisis (Problems Identified)
    # =========================================================================
    s2 = add_base_slide(
        "Slide 02 • Threat Analysis & Problem Definition",
        "Why Legacy Payment Rails Fail Autonomous AI Agents",
        "5 Structural Vulnerabilities When Non-Deterministic LLMs Interface with Corporate Cards",
    )

    threats = [
        ("1. Unbounded Spending Loops", "When an autonomous agent is caught in an error-recovery, recursive retry, or search loop, programmatic card requests can drain corporate limits in minutes without human detection.", RED),
        ("2. Prompt Injection Exploits", "Adversarial inputs on merchant websites or indirect prompt injections manipulate LLM decision-making into approving fraudulent, unauthorized, or inflated transactions.", AMBER),
        ("3. Concurrency & Double-Spend Races", "Independent agent worker threads operating concurrently execute simultaneous checkouts that bypass optimistic balance checks, resulting in negative ledger balances.", RED),
        ("4. Zero Audit Provenance", "Standard HTTP logs capture timestamps and IP addresses but cannot explain *why* an agent made a decision, rendering forensic root-cause analysis impossible.", BRIGHT_CYAN),
    ]

    for i, (title, desc, col) in enumerate(threats):
        x = Inches(0.8 + (i % 2) * 6.0)
        y = Inches(1.9 + (i // 2) * 2.4)
        add_card(s2, x, y, Inches(5.733), Inches(2.2), title, border_color=col)
        tb = s2.shapes.add_textbox(x + Inches(0.2), y + Inches(0.65), Inches(5.333), Inches(1.4))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.size = Pt(11)
        p.font.color.rgb = WHITE

    # Bottom summary banner
    add_card(s2, Inches(0.8), Inches(6.1), Inches(11.733), Inches(0.75), bg_color=CARD_INNER)
    tb = s2.shapes.add_textbox(Inches(1.0), Inches(6.2), Inches(11.333), Inches(0.55))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "Result: Payment processors hold merchants and enterprises strictly liable. Without cryptographic proof connecting agent intent to fulfillment, chargebacks are lost automatically."
    p.font.size = Pt(10.5)
    p.font.bold = True
    p.font.color.rgb = AMBER

    # =========================================================================
    # SLIDE 3: Gaps Solved & Competitive Analysis Matrix
    # =========================================================================
    s3 = add_base_slide(
        "Slide 03 • Market Gaps & Differentiation",
        "Architectural Comparison: AEGIS vs. Legacy Rails",
        "Why Traditional Gateways and Virtual Cards Fall Short for Autonomous Workloads",
    )

    # Table
    rows = 7
    cols = 4
    left = Inches(0.8)
    top = Inches(1.9)
    width = Inches(11.733)
    height = Inches(4.8)

    table_shape = s3.shapes.add_table(rows, cols, left, top, width, height)
    table = table_shape.table
    table.columns[0].width = Inches(2.4)
    table.columns[1].width = Inches(3.1)
    table.columns[2].width = Inches(3.1)
    table.columns[3].width = Inches(3.133)

    headers = ["Dimension", "Legacy Gateways (Stripe/PayPal)", "Virtual Cards (Brex/Ramp)", "AEGIS Platform"]
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(14, 30, 56)
        p = cell.text_frame.paragraphs[0]
        p.text = h
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = BRIGHT_CYAN

    data = [
        ("Spending Governance", "None (Static card limit)", "Static monthly spend cap", "Deterministic Passports & Dynamic Velocity Limits"),
        ("Authorization Model", "Card swipe releases funds", "Basic merchant category code", "Deterministic Policy Engine (Zero LLM Authorization)"),
        ("Concurrency Control", "Optimistic (Race vulnerable)", "Gateway balance check", "PostgreSQL Advisory Locks (pg_advisory_xact_lock)"),
        ("Forensic Auditability", "Plaintext HTTP server logs", "Monthly statement CSV", "SHA-256 Merkle Hash-Chained Audit Ledger"),
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
            p.font.size = Pt(9.5)
            p.font.color.rgb = GREEN if j == 3 else (WHITE if j > 0 else BRIGHT_CYAN)
            if j == 3:
                p.font.bold = True

    # =========================================================================
    # SLIDE 4: Core Novelty & System Architecture
    # =========================================================================
    s4 = add_base_slide(
        "Slide 04 • System Topology & Decomposition",
        "The Tri-Subsystem Model: Guardian, GhostPay & DisputeOS",
        "Sovereign Subsystems Governing the Complete Autonomous Transaction Lifecycle",
    )

    subsystems = [
        ("1. AgentPay Guardian", "AUTONOMOUS GOVERNANCE & EXECUTION", [
            "Deterministic Spending Passports with tiered budgets.",
            "Velocity caps & mandatory human escalation thresholds.",
            "Atomic ledger budget reservation with advisory locks.",
            "PayPal Orders v2 sandbox integration with capture guards.",
        ], BRIGHT_CYAN),
        ("2. GhostPay Forensics", "IMMUTABLE AUDIT & FORENSIC REPLAY", [
            "Cryptographic SHA-256 Merkle hash-chained ledger.",
            "Deterministic replay simulator for past transaction states.",
            "Counterfactual policy simulator ('What-if' risk bounds).",
            "Agent DNA profiling for behavioral drift & anomaly detection.",
        ], GREEN),
        ("3. DisputeOS Engine", "CHARGEBACK DEFENSE & EVIDENCE GRAPHS", [
            "Automated dispute case assembly via PayPal webhooks.",
            "Multimodal evidence graph (server telemetry, delivery ARNs).",
            "Contradiction detection cross-referencing claims with logs.",
            "Grounded AI defense briefs with 100% citation confidence.",
        ], AMBER),
    ]

    for i, (title, sub, points, col) in enumerate(subsystems):
        x = Inches(0.8 + i * 4.0)
        add_card(s4, x, Inches(1.9), Inches(3.733), Inches(4.9), title, border_color=col)
        tb = s4.shapes.add_textbox(x + Inches(0.2), Inches(2.4), Inches(3.333), Inches(4.2))
        tf = tb.text_frame
        tf.word_wrap = True

        p_sub = tf.paragraphs[0]
        p_sub.text = sub
        p_sub.font.size = Pt(8.5)
        p_sub.font.bold = True
        p_sub.font.color.rgb = col

        for pt in points:
            p = tf.add_paragraph()
            p.text = f"• {pt}"
            p.font.size = Pt(10.5)
            p.font.color.rgb = WHITE
            p.space_before = Pt(8)

    # =========================================================================
    # SLIDE 5: Data Flow Architecture (DFD Level 0 & Level 1)
    # =========================================================================
    s5 = add_base_slide(
        "Slide 05 • Data Flow Architecture",
        "Level 0 Context & Level 1 System Data Flow",
        "Traceability from Agent Proposal Submission to Immutable Ledger Settlement",
    )

    # DFD Level 0 Box (Top Half)
    add_card(s5, Inches(0.8), Inches(1.9), Inches(11.733), Inches(2.1), "Level 0 Context Data Flow (System Boundary)")
    l0_steps = [
        ("Autonomous AI Agent", "Submits purchase proposal with quote items"),
        ("AEGIS Platform", "Enforces policy bounds & advisory locks"),
        ("Human Approver", "Digital sign-off on out-of-policy requests"),
        ("PayPal Sandbox Rail", "Creates Orders v2 & executes capture"),
        ("GhostPay Ledger", "Appends SHA-256 Merkle audit proof"),
    ]
    for i, (box_title, box_sub) in enumerate(l0_steps):
        bx = Inches(1.0 + i * 2.3)
        add_card(s5, bx, Inches(2.45), Inches(2.1), Inches(1.3), box_title, bg_color=CARD_INNER, border_color=BRIGHT_CYAN)
        tb = s5.shapes.add_textbox(bx + Inches(0.1), Inches(2.9), Inches(1.9), Inches(0.8))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = box_sub
        p.font.size = Pt(8.5)
        p.font.color.rgb = MUTED

    # DFD Level 1 Box (Bottom Half)
    add_card(s5, Inches(0.8), Inches(4.2), Inches(11.733), Inches(2.6), "Level 1 Decomposed Pipeline Architecture")
    l1_stages = [
        ("1. Ingestion Pipeline", "FastAPI router validates Pydantic v2 schemas and computes deterministic quote hash."),
        ("2. Policy Evaluation", "Evaluates velocity caps and single-tx limits against spending passport constraints."),
        ("3. Concurrency Lock", "Acquires pg_advisory_xact_lock on passport UUID, preventing double-spend."),
        ("4. Payment Rail Dispatch", "Invokes PayPal REST v2 API with idempotency key, creating sandbox order."),
        ("5. Merkle Event Chaining", "Transactional outbox worker commits event to SHA-256 Merkle audit chain."),
    ]
    for i, (stg_t, stg_d) in enumerate(l1_stages):
        bx = Inches(1.0 + i * 2.3)
        add_card(s5, bx, Inches(4.75), Inches(2.1), Inches(1.85), stg_t, bg_color=CARD_INNER, border_color=GREEN)
        tb = s5.shapes.add_textbox(bx + Inches(0.1), Inches(5.2), Inches(1.9), Inches(1.3))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = stg_d
        p.font.size = Pt(8.5)
        p.font.color.rgb = WHITE

    # =========================================================================
    # SLIDE 6: End-to-End Transaction Sequence
    # =========================================================================
    s6 = add_base_slide(
        "Slide 06 • Protocol Execution Sequence",
        "End-to-End Autonomous Transaction Protocol",
        "Proposal Validation, Advisory Locking, PayPal Order Creation, Premature Capture Guard & Settlement",
    )

    steps = [
        ("Step 1: Proposal & Quote Normalization", "Agent submits purchase proposal. AEGIS computes deterministic quote hash H_quote = SHA-256(canonical_json(quote_items)).", BRIGHT_CYAN),
        ("Step 2: Deterministic Policy Evaluation", "Evaluates spending velocity, merchant allowlist, and per-tx limits. If proposal <= threshold ($15 < $25), auto-approves to CHECKOUT_READY.", GREEN),
        ("Step 3: Human Escalation Gate", "If proposal > threshold ($750 > $500), execution halts in AWAITING_APPROVAL until digital owner sign-off.", AMBER),
        ("Step 4: Atomic Budget Reservation", "Executes SELECT pg_advisory_xact_lock(hashtext(passport_id)) and commits balance reservation in Neon PostgreSQL.", BRIGHT_CYAN),
        ("Step 5: PayPal Orders v2 Dispatch", "Creates live PayPal Sandbox order (e.g. 6A285669PT3485328). Enforces capture guard: premature capture returns 409 Conflict.", AMBER),
        ("Step 6: HMAC Webhook & Merkle Settlement", "Inbound webhook verified via HMAC-SHA256 fail-closed signature. Settles ledger and chains event in GhostPay audit ledger.", GREEN),
    ]

    for i, (title, desc, col) in enumerate(steps):
        x = Inches(0.8 + (i % 2) * 6.0)
        y = Inches(1.9 + (i // 2) * 1.65)
        add_card(s6, x, y, Inches(5.733), Inches(1.45), title, border_color=col)
        tb = s6.shapes.add_textbox(x + Inches(0.2), y + Inches(0.55), Inches(5.333), Inches(0.85))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.size = Pt(9.5)
        p.font.color.rgb = WHITE

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
            "PostgreSQL row-level lock released automatically upon transaction commit.",
        ], GREEN),
        ("2. Two-Phase Budget Reservation", [
            "Formula: Available = Budget - (Settled + Reserved)",
            "Budget is atomically reserved BEFORE external API dispatch.",
            "Rolls back cleanly without balance leakage if upstream order expires.",
            "Guarantees that active agent swarms never drive balances negative.",
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
        y = Inches(1.9 + (i // 2) * 2.45)
        add_card(s7, x, y, Inches(5.733), Inches(2.25), title, border_color=col)
        tb = s7.shapes.add_textbox(x + Inches(0.2), y + Inches(0.6), Inches(5.333), Inches(1.5))
        tf = tb.text_frame
        tf.word_wrap = True
        for pt in pts:
            p = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
            p.text = f"• {pt}"
            p.font.size = Pt(9.5)
            p.font.color.rgb = WHITE
            p.space_before = Pt(3)

    # =========================================================================
    # SLIDE 8: Enterprise Security Architecture & Threat Model (STRIDE)
    # =========================================================================
    s8 = add_base_slide(
        "Slide 08 • Security Architecture & STRIDE Model",
        "Enterprise Security Architecture & STRIDE Threat Analysis",
        "Hardened Defense-in-Depth Against Adversarial Agent Prompts and Financial Exploits",
    )

    stride = [
        ("SPOOFING", "Asymmetric JWT & Scoped API Keys. Strict tenant_id isolation enforced on every query.", GREEN),
        ("TAMPERING", "SHA-256 Merkle hash-chaining: H_n = SHA-256(H_{n-1} || E_n) detects any historical write.", BRIGHT_CYAN),
        ("REPUDIATION", "Digital owner signatures logged with actor_id, correlation_id, and immutable timestamps.", AMBER),
        ("INFO DISCLOSURE", "PII/PCI scrubbing on quote descriptions; non-reversible tokenization of PayPal receivers.", GREEN),
        ("DENIAL OF SERVICE", "Upstash Redis distributed token-bucket rate limiter per agent UUID and client IP.", BRIGHT_CYAN),
        ("ELEVATION OF PRIVILEGE", "Prompt Injection Defense: Model tokens stripped; external data isolated in strict XML.", RED),
    ]

    for i, (threat, mit, col) in enumerate(stride):
        x = Inches(0.8 + (i % 3) * 4.0)
        y = Inches(1.9 + (i // 3) * 1.6)
        add_card(s8, x, y, Inches(3.733), Inches(1.4), threat, border_color=col)
        tb = s8.shapes.add_textbox(x + Inches(0.15), y + Inches(0.5), Inches(3.433), Inches(0.85))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = mit
        p.font.size = Pt(9.5)
        p.font.color.rgb = WHITE

    # Prompt Injection Sanitization Callout
    add_card(s8, Inches(0.8), Inches(5.3), Inches(11.733), Inches(1.45), "Prompt Injection Sanitization & Fail-Closed Guard", border_color=RED)
    tb = s8.shapes.add_textbox(Inches(1.0), Inches(5.8), Inches(11.333), Inches(0.85))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "• XML Delimitation: All untrusted strings are enclosed inside <untrusted_input trust=\"UNTRUSTED_DATA\"> with angle brackets escaped.\n• Zero LLM Financial Authority: LLMs generate summary text but CANNOT approve budgets, override limits, or invoke capture.\n• Fail-Closed LLM Fallback: If an upstream LLM experiences 429 quota limits or prompt anomalies, DisputeOS automatically degrades to deterministic-rules-v1 with 100% uptime."
    p.font.size = Pt(9.5)
    p.font.color.rgb = WHITE

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
        y = Inches(1.9 + (i // 2) * 2.1)
        add_card(s9, x, y, Inches(5.733), Inches(1.9), title, border_color=col)
        tb = s9.shapes.add_textbox(x + Inches(0.2), y + Inches(0.6), Inches(5.333), Inches(1.2))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.size = Pt(10.5)
        p.font.color.rgb = WHITE

    # Live Verified Evidence Callout Box
    add_card(s9, Inches(0.8), Inches(6.15), Inches(11.733), Inches(0.75), bg_color=CARD_INNER, border_color=GREEN)
    tb = s9.shapes.add_textbox(Inches(1.0), Inches(6.25), Inches(11.333), Inches(0.55))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "Verified Live Proof: Investigation 4cce42a3-881d-43d7-aae5-3f32537c97eb confirmed status VALID across 5 sequential event blocks (PROPOSAL_SUBMITTED -> POLICY_EVALUATED -> BUDGET_RESERVED -> PAYPAL_ORDER_CREATED -> CAPTURE_COMPLETED)."
    p.font.size = Pt(9.5)
    p.font.bold = True
    p.font.color.rgb = GREEN

    # =========================================================================
    # SLIDE 10: DisputeOS Contradiction Matrix & Grounded Defense
    # =========================================================================
    s10 = add_base_slide(
        "Slide 10 • Dispute Resolution & Chargeback Defense",
        "DisputeOS: Automated Evidence Graphs & Contradiction Defense",
        "Eliminating Chargeback Losses via Multimodal Telemetry and Grounded Citations",
    )

    disp_cards = [
        ("1. Automated Evidence Ingestion", "Automatically ingests server access logs, API consumption telemetry, signed delivery receipts, and carrier tracking IDs upon dispute notification from PayPal.", BRIGHT_CYAN),
        ("2. Contradiction Detection Engine", "Cross-references buyer dispute claims against technical telemetry. Flags direct logical contradictions (e.g. buyer claims non-delivery, but telemetry shows active API consumption).", GREEN),
        ("3. Grounded AI Defense Briefs", "Compiles structured chargeback defense packets with verified source citations, confidence scores, and strict rejection of ungrounded model hallucinations.", AMBER),
        ("4. Human Reviewer Governance", "Defense briefs require compliance officer review and digital sign-off before electronic transmission to card networks, ensuring 100% human accountability.", GREEN),
    ]

    for i, (title, desc, col) in enumerate(disp_cards):
        x = Inches(0.8 + (i % 2) * 6.0)
        y = Inches(1.9 + (i // 2) * 2.1)
        add_card(s10, x, y, Inches(5.733), Inches(1.9), title, border_color=col)
        tb = s10.shapes.add_textbox(x + Inches(0.2), y + Inches(0.6), Inches(5.333), Inches(1.2))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.size = Pt(10.5)
        p.font.color.rgb = WHITE

    # Live Case Contradiction Evidence Box
    add_card(s10, Inches(0.8), Inches(6.15), Inches(11.733), Inches(0.75), bg_color=CARD_INNER, border_color=AMBER)
    tb = s10.shapes.add_textbox(Inches(1.0), Inches(6.25), Inches(11.333), Inches(0.55))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "Verified Live Dispute Case b4502263: Buyer claimed 'Item Not Received' for 2.5M Token Batch Capacity. Contradiction Engine matched openai_workspace_quota_telemetry.json proving 42.8% token consumption within 14 mins of order settlement."
    p.font.size = Pt(9.5)
    p.font.bold = True
    p.font.color.rgb = AMBER

    # =========================================================================
    # SLIDE 11: Production Verification Evidence, Quality Scorecard & Roadmap
    # =========================================================================
    s11 = add_base_slide(
        "Slide 11 • Operational Maturity & Commercial Roadmap",
        "Measured Production Evidence & Commercial Roadmap",
        "Rigorous Empirical Verification, Latency SLAs, and Enterprise Scaling Milestones",
    )

    # 4 Scorecard Metrics
    scorecard = [
        ("354 / 354", "AUTOMATED TESTS", "90%+ Statement Coverage", GREEN),
        ("8 / 8", "LIVE CLOUD SUITES", "100% Staging Verification", BRIGHT_CYAN),
        ("< 45ms", "POLICY LATENCY SLA", "Strict P99 Response Time", AMBER),
        ("0", "CONCURRENCY DEADLOCKS", "18 Multi-Thread Stress Runs", GREEN),
    ]

    for i, (val, label, sub, col) in enumerate(scorecard):
        x = Inches(0.8 + i * 3.0)
        add_card(s11, x, Inches(1.9), Inches(2.733), Inches(1.4), bg_color=CARD_BG, border_color=col)
        tb = s11.shapes.add_textbox(x + Inches(0.15), Inches(2.0), Inches(2.433), Inches(1.2))
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

    # Live Cloud Infrastructure Box
    add_card(s11, Inches(0.8), Inches(3.5), Inches(11.733), Inches(1.4), "Live Staging Cloud Topology (Azure, Neon, Upstash, PayPal)")
    tb = s11.shapes.add_textbox(Inches(1.0), Inches(3.95), Inches(11.333), Inches(0.85))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "• Azure Ubuntu Staging VM (20.124.91.36): Nginx SSL reverse proxy, Docker Compose container stack.\n• Neon Serverless PostgreSQL (Ohio v18.6): SSL connection pooler, SQLAlchemy 2.0 ORM, Alembic migrations.\n• Upstash Managed Redis (v8.4.0 TLS rediss://): Token-bucket rate limiting, distributed caching, worker queues.\n• PayPal Sandbox Orders v2: Real REST OAuth token rotation, order capture guards, fail-closed webhook security."
    p.font.size = Pt(9.5)
    p.font.color.rgb = WHITE

    # Strategic Roadmap Box
    add_card(s11, Inches(0.8), Inches(5.1), Inches(11.733), Inches(1.75), "Strategic Commercial Roadmap (2027)")
    roadmap_quarters = [
        ("Q1 2027: Multi-Rail Expansion", "Stripe Agentic & Virtual Card issuing integration; Adyen & Visa B2B connectors."),
        ("Q2 2027: Enterprise Compliance", "SOC 2 Type II certification; ISO 27001 audit; Splunk / Datadog audit apps."),
        ("Q3 2027: Swarm Consensus", "Multi-agent collaborative spending pools with threshold cryptographic keys."),
        ("Q4 2027: Sovereign Cloud", "Enterprise On-Premises & Sovereign Cloud Helm Kubernetes packaging."),
    ]
    for i, (q_title, q_desc) in enumerate(roadmap_quarters):
        bx = Inches(1.0 + i * 2.85)
        add_card(s11, bx, Inches(5.6), Inches(2.7), Inches(1.1), bg_color=CARD_INNER, border_color=BRIGHT_CYAN)
        tb = s11.shapes.add_textbox(bx + Inches(0.1), Inches(5.65), Inches(2.5), Inches(0.95))
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

    # Save
    out_path = "/home/bigboyaks/Downloads/AEGIS_Master_Presentation.pptx"
    prs.save(out_path)
    prs.save("/home/bigboyaks/Projects/agentpay-nexus/AEGIS_Master_Presentation.pptx")
    print(f"Master presentation saved to {out_path} and workspace successfully!")


if __name__ == "__main__":
    create_deck()
