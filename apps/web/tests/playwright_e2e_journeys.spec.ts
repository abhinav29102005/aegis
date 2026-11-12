import { expect, test, type Page } from "@playwright/test";

/**
 * Comprehensive Real-Chromium Playwright E2E Test Suite (Workstream C)
 *
 * Covers all 5 required browser journeys against a live Next.js + FastAPI + PostgreSQL stack:
 * 1. Authentication & Organizations
 * 2. Guardian (Agents, Merchants, Passports, Proposals, Policy, Approve/Reject, Checkout)
 * 3. GhostPay (Replay, Provenance Timeline, Counterfactual Simulation, VIEWER RBAC rejection)
 * 4. DisputeOS (Create Case, Evidence & Artifact Upload, Provenance Graph, Analysis, Report, Approve, Synthetic Guard, Resolve)
 * 5. Developer Platform, Settings (Billing/Quotas & GDPR/DPDPA Privacy), Status & Legal
 */

interface RuntimeMonitorOptions {
  allowHttpStatuses?: number[];
}

interface RuntimeMonitor {
  assertClean: () => void;
}

function attachRuntimeMonitors(
  page: Page,
  options: RuntimeMonitorOptions = {},
): RuntimeMonitor {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const serverErrors: string[] = [];
  const allowedStatuses = new Set(options.allowHttpStatuses ?? []);

  page.on("pageerror", (err) => {
    pageErrors.push(`pageerror: ${err.message}`);
  });

  page.on("console", (msg) => {
    const text = msg.text();
    const isHydrationError =
      /hydration/i.test(text) &&
      /(error|mismatch|did not match|failed)/i.test(text);

    if (msg.type() === "error" || isHydrationError) {
      // Chromium logs a console error for intentional 401/403 network checks (e.g. unauthenticated /api/auth/me or RBAC).
      if (/Failed to load resource: the server responded with a status of (\d{3})/.test(text)) {
        const match = text.match(/status of (\d{3})/);
        const statusCode = match ? Number(match[1]) : 0;
        if (
          allowedStatuses.has(statusCode) ||
          (statusCode === 401 && page.url().includes("/login"))
        ) {
          return;
        }
      }
      consoleErrors.push(`console.${msg.type()}: ${text}`);
    }
  });

  page.on("requestfailed", (req) => {
    const failure = req.failure()?.errorText ?? "unknown";
    // Ignore aborted requests caused by intentional client-side redirects/navigation.
    if (failure === "net::ERR_ABORTED") {
      return;
    }
    failedRequests.push(`${req.method()} ${req.url()} -> ${failure}`);
  });

  page.on("response", (res) => {
    if (res.status() >= 500 || res.status() === 404) {
      serverErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`);
    }
  });

  return {
    assertClean: () => {
      const problems = [
        ...pageErrors,
        ...consoleErrors,
        ...failedRequests,
        ...serverErrors,
      ];
      expect(
        problems,
        `Unexpected browser/network errors:\n${problems.join("\n")}`,
      ).toEqual([]);
    },
  };
}

function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

async function registerOrganization(
  page: Page,
  opts: {
    email: string;
    password: string;
    fullName: string;
    orgName: string;
    orgSlug: string;
  },
): Promise<void> {
  await page.goto("/login");
  await page.getByRole("tab", { name: "Create Organization" }).click();
  await page.locator("#full-name").fill(opts.fullName);
  await page.locator("#org-name").fill(opts.orgName);
  await page.locator("#org-slug").fill(opts.orgSlug);
  await page.locator("#email").fill(opts.email);
  await page.locator("#password").fill(opts.password);
  await page.getByRole("button", { name: "Create Organization & Continue" }).click();
  await page.waitForURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Platform Overview" })).toBeVisible();
}

async function loginWithCredentials(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByRole("tab", { name: "Sign In" }).click();
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign In to Organization" }).click();
  await page.waitForURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Platform Overview" })).toBeVisible();
}

async function setupGuardianEntities(
  page: Page,
  suffix: string,
): Promise<{
  agentName: string;
  merchantName: string;
  paymentIntentId: string;
}> {
  const agentName = `Agent-${suffix}`;
  const merchantName = `Merchant-${suffix}`;
  const merchantDomain = `${suffix}.example.com`;

  // 1. Register AI Agent & Add Allowlisted Merchant
  await page.goto("/agents");
  await page.locator("#agent-name").fill(agentName);
  await page.locator("#agent-framework").selectOption("langgraph");
  await page.locator("#agent-purpose").fill("Automated SaaS procurement");
  await page.getByRole("button", { name: "Register Agent" }).click();
  await expect(page.getByText(agentName).first()).toBeVisible();

  await page.locator("#m-name").fill(merchantName);
  await page.locator("#m-domain").fill(merchantDomain);
  await page.locator("#m-cat").fill("saas");
  await page.getByRole("button", { name: "Add Merchant" }).click();
  await expect(page.getByText(merchantName).first()).toBeVisible();

  // 2. Issue Spending Passport
  await page.goto("/passports");
  await expect(page.locator("#pp-agent option", { hasText: agentName })).toHaveCount(1);
  const agentOptionVal = await page
    .locator("#pp-agent option", { hasText: agentName })
    .first()
    .getAttribute("value");
  if (!agentOptionVal) {
    throw new Error(`Could not find option value for agent ${agentName}`);
  }
  await page.locator("#pp-agent").selectOption(agentOptionVal);
  await page.locator("#pp-total").fill("1000");
  await page.locator("#pp-pertx").fill("500");
  await page.locator("#pp-daily").fill("800");
  await page.locator("#pp-thresh").fill("100");
  await page.locator("#pp-cats").fill("saas");

  // Select the merchant checkbox if listed
  const merchantCheckbox = page
    .locator("fieldset label", { hasText: merchantName })
    .locator("input[type='checkbox']");
  if ((await merchantCheckbox.count()) > 0) {
    await merchantCheckbox.check();
  }

  const passportRespPromise = page.waitForResponse(
    (res) =>
      res.url().includes("/api/proxy/guardian/passports") &&
      res.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Issue Spending Passport" }).click();
  const passportResp = await passportRespPromise;
  expect(passportResp.status()).toBeLessThan(400);

  // 3. Propose Purchase on /payments (amount $150 > $100 human approval threshold)
  await page.goto("/payments");
  await page.locator("#proposal-agent").selectOption(agentOptionVal);
  const merchantOptionVal = await page
    .locator("#proposal-merchant option", { hasText: merchantName })
    .first()
    .getAttribute("value");
  if (!merchantOptionVal) {
    throw new Error(`Could not find option value for merchant ${merchantName}`);
  }
  await page.locator("#proposal-merchant").selectOption(merchantOptionVal);
  await page.locator("#proposal-amount").fill("150.00");
  await page.locator("#proposal-summary").fill(`Cloud License ${suffix}`);
  await page.locator("#proposal-rationale").fill("RC1 E2E procurement verification");

  const proposalResponsePromise = page.waitForResponse(
    (res) =>
      res.url().includes("/api/proxy/guardian/proposals") &&
      res.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Submit Proposal" }).click();
  const proposalResp = await proposalResponsePromise;
  expect(proposalResp.status()).toBeLessThan(400);
  const proposalJson = (await proposalResp.json()) as {
    payment_intent?: { id: string };
    id?: string;
  };
  const paymentIntentId = proposalJson.payment_intent?.id ?? proposalJson.id ?? "";
  expect(paymentIntentId).toBeTruthy();

  return { agentName, merchantName, paymentIntentId };
}

test.describe("Workstream C: Real Chromium E2E Journeys", () => {
  test("Journey 1: Authentication, HttpOnly Session, Org Switching, Reload Persistence, Logout & Role UI", async ({
    page,
  }) => {
    const monitor = attachRuntimeMonitors(page, { allowHttpStatuses: [401] });
    const id = uniqueId("auth");
    const ownerEmail = `owner-${id}@acme-e2e.internal`;
    const viewerEmail = `viewer-${id}@acme-e2e.internal`;
    const password = "StrongPassword!123";
    const org1Name = `Acme Primary ${id}`;
    const org1Slug = `acme-1-${id}`;
    const org2Name = `Acme Secondary ${id}`;
    const org2Slug = `acme-2-${id}`;

    // 1. Protected routes redirect to /login when logged out
    await page.goto("/dashboard");
    await page.waitForURL(/\/login/);
    await page.goto("/payments");
    await page.waitForURL(/\/login\?next=%2Fpayments/);

    // 2. Register organization & verify HttpOnly cookie
    await registerOrganization(page, {
      email: ownerEmail,
      password,
      fullName: "E2E Owner",
      orgName: org1Name,
      orgSlug: org1Slug,
    });

    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find((c) => c.name === "aegis_session");
    expect(sessionCookie, "aegis_session cookie should be set").toBeDefined();
    expect(sessionCookie?.httpOnly).toBe(true);

    // 3. Create second organization via header modal, switch orgs, and verify reload persistence
    await page.locator('button[title="Create New Organization"]').click();
    await expect(page.getByRole("dialog", { name: "Create Organization" })).toBeVisible();
    await page.locator("#modal-org-name").fill(org2Name);
    await page.locator("#modal-org-slug").fill(org2Slug);
    const createSwitchPromise = page.waitForResponse(
      (res) => res.url().includes("/api/auth/switch-org") && res.status() === 200,
    );
    await page.getByRole("button", { name: "Create & Switch" }).click();
    await createSwitchPromise;

    await expect(page.locator("#org-switcher option")).toHaveCount(2);
    const selectedAfterCreate = await page.locator("#org-switcher").inputValue();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Platform Overview" })).toBeVisible();
    expect(await page.locator("#org-switcher").inputValue()).toBe(selectedAfterCreate);

    // Switch back to first org and verify persistence across reload
    const firstOrgOption = page.locator("#org-switcher option", { hasText: org1Name });
    const firstOrgId = await firstOrgOption.getAttribute("value");
    expect(firstOrgId).toBeTruthy();
    const switchBackPromise = page.waitForResponse(
      (res) => res.url().includes("/api/auth/switch-org") && res.status() === 200,
    );
    await page.locator("#org-switcher").selectOption(firstOrgId!);
    await switchBackPromise;
    await page.reload();
    expect(await page.locator("#org-switcher").inputValue()).toBe(firstOrgId);

    // 4. Add a VIEWER member in /settings to verify role-based UI visibility
    await page.goto("/settings");
    await page.getByRole("button", { name: /Team & RBAC/ }).click();
    await page.getByLabel("Member email").fill(viewerEmail);
    await page.getByLabel("Member full name").fill("E2E Viewer");
    await page.getByLabel("Initial password").fill(password);
    await page.getByLabel("Canonical Role").selectOption("VIEWER");
    await page.getByRole("button", { name: "Add Member" }).click();
    await expect(page.getByText(viewerEmail)).toBeVisible();

    // 5. Logout clears session and redirects to /login
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login/);
    const cookiesAfterLogout = await page.context().cookies();
    expect(cookiesAfterLogout.find((c) => c.name === "aegis_session")).toBeUndefined();

    // 6. Login as VIEWER and verify role-based UI visibility restrictions
    await loginWithCredentials(page, viewerEmail, password);
    await expect(page.locator("aside").getByText("VIEWER", { exact: true })).toBeVisible();

    await page.goto("/agents");
    await expect(page.getByRole("heading", { name: "Register AI Agent" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Add Allowlisted Merchant" })).toHaveCount(0);

    await page.goto("/passports");
    await expect(page.getByRole("heading", { name: "Issue New Spending Passport" })).toHaveCount(0);

    await page.goto("/payments");
    await expect(page.getByRole("heading", { name: "Submit New Purchase Proposal" })).toHaveCount(0);

    // 7. Expired / invalid session cookie triggers redirect to /login
    await page.context().clearCookies();
    await page.context().addCookies([
      {
        name: "aegis_session",
        value: "expired.invalid.jwt.token",
        domain: "127.0.0.1",
        path: "/",
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    await page.goto("/dashboard");
    await page.waitForURL(/\/login/);

    monitor.assertClean();
  });

  test("Journey 2: Guardian Agent, Merchant, Passport, Proposal Policy, Approve & Reject Flows, and Checkout", async ({
    page,
  }) => {
    const monitor = attachRuntimeMonitors(page, { allowHttpStatuses: [400] });
    const id = uniqueId("guard");

    await registerOrganization(page, {
      email: `owner-${id}@acme-e2e.internal`,
      password: "StrongPassword!123",
      fullName: "Guardian Owner",
      orgName: `Guardian Org ${id}`,
      orgSlug: `guard-${id}`,
    });

    // Proposal 1 -> Inspect /payments/[id] -> Reject (approved: false)
    const { agentName, merchantName, paymentIntentId: rejectedId } =
      await setupGuardianEntities(page, id);

    await page.goto(`/payments/${rejectedId}`);
    await expect(page.getByText("Proposal & Immutable Quote")).toBeVisible();
    await expect(page.getByText("Policy Decision, Approval & Reservation")).toBeVisible();
    await expect(page.getByText("AWAITING_APPROVAL").first()).toBeVisible();

    await page.getByRole("button", { name: "Decline / Reject" }).click();
    const rejectDialog = page.locator("dialog[open]");
    await expect(rejectDialog).toBeVisible();
    await rejectDialog.getByRole("button", { name: "Reject Proposal" }).click();
    await expect(rejectDialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Decline / Reject" })).toHaveCount(0);

    // Proposal 2 -> Inspect /payments/[id] -> Approve & Reserve -> Initiate Checkout
    await page.goto("/payments");
    const agentVal = await page
      .locator("#proposal-agent option", { hasText: agentName })
      .first()
      .getAttribute("value");
    const merchantVal = await page
      .locator("#proposal-merchant option", { hasText: merchantName })
      .first()
      .getAttribute("value");
    await page.locator("#proposal-agent").selectOption(agentVal!);
    await page.locator("#proposal-merchant").selectOption(merchantVal!);
    await page.locator("#proposal-amount").fill("150.00");
    await page.locator("#proposal-summary").fill(`Approved Purchase ${id}`);
    await page.locator("#proposal-rationale").fill("Approved E2E flow");

    const approveProposalPromise = page.waitForResponse(
      (res) =>
        res.url().includes("/api/proxy/guardian/proposals") &&
        res.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Submit Proposal" }).click();
    const approveProposalJson = (await (await approveProposalPromise).json()) as {
      payment_intent?: { id: string };
      id?: string;
    };
    const approvedId = approveProposalJson.payment_intent?.id ?? approveProposalJson.id!;

    await page.goto(`/payments/${approvedId}`);
    await expect(page.getByText("AWAITING_APPROVAL").first()).toBeVisible();

    await page.getByRole("button", { name: "Approve & Reserve" }).click();
    const approveDialog = page.locator("dialog[open]");
    await expect(approveDialog).toBeVisible();
    await approveDialog.getByRole("button", { name: "Approve & Reserve" }).click();
    await expect(approveDialog).toHaveCount(0);

    const checkoutBtn = page.getByRole("button", { name: "Initiate Checkout" });
    await expect(checkoutBtn).toBeVisible();

    const checkoutRespPromise = page.waitForResponse(
      (res) =>
        res.url().includes(`/api/proxy/guardian/payments/${approvedId}/checkout`) &&
        res.request().method() === "POST",
    );
    await checkoutBtn.click();
    const checkoutResp = await checkoutRespPromise;
    expect(checkoutResp.status()).toBeLessThan(500);

    if (checkoutResp.ok()) {
      await expect(page.getByText("AWAITING_PAYPAL_BUYER").first()).toBeVisible();
      await expect(
        page.getByRole("link", { name: /Proceed to PayPal Checkout/ }),
      ).toBeVisible();
    } else {
      // Unconfigured PayPal sandbox returns a 4xx cleanly surfaced via role="alert"
      await expect(page.locator("[role='alert']").first()).toBeVisible();
    }

    monitor.assertClean();
  });

  test("Journey 3: GhostPay Replay, Provenance Timeline, Counterfactual Simulation & VIEWER Rejection", async ({
    page,
  }) => {
    const monitor = attachRuntimeMonitors(page, { allowHttpStatuses: [403] });
    const id = uniqueId("ghost");
    const ownerEmail = `owner-${id}@acme-e2e.internal`;
    const viewerEmail = `viewer-${id}@acme-e2e.internal`;
    const password = "StrongPassword!123";

    await registerOrganization(page, {
      email: ownerEmail,
      password,
      fullName: "GhostPay Owner",
      orgName: `GhostPay Org ${id}`,
      orgSlug: `ghost-${id}`,
    });

    const { paymentIntentId } = await setupGuardianEntities(page, id);

    // Add VIEWER user for unauthorized simulation test
    await page.goto("/settings");
    await page.getByRole("button", { name: /Team & RBAC/ }).click();
    await page.getByLabel("Member email").fill(viewerEmail);
    await page.getByLabel("Member full name").fill("GhostPay Viewer");
    await page.getByLabel("Initial password").fill(password);
    await page.getByLabel("Canonical Role").selectOption("VIEWER");
    await page.getByRole("button", { name: "Add Member" }).click();
    await expect(page.getByText(viewerEmail)).toBeVisible();

    // Launch Forensic Replay from /ghostpay
    await page.goto("/ghostpay");
    await page.locator("#replay-intent-select").selectOption(paymentIntentId);
    await page.getByRole("button", { name: "Inspect Replay & Counterfactuals" }).click();
    await page.waitForURL(new RegExp(`/ghostpay/replay/${paymentIntentId}`));

    // Inspect provenance timeline
    await expect(page.getByRole("heading", { name: /Provenance Timeline/ })).toBeVisible();
    await expect(page.getByText("#1").first()).toBeVisible();
    await expect(page.getByText(/Hash:/).first()).toBeVisible();

    // Run Counterfactual Policy Simulation (lower per-tx limit to $50 so $150 fails policy)
    await page.locator("#sim-per-tx").fill("50");
    await page.locator("#sim-threshold").fill("25");
    await page.getByRole("button", { name: "Run Counterfactual" }).click();

    await expect(page.getByText("Counterfactual Result")).toBeVisible();
    await expect(page.getByText("Changed constraints:")).toBeVisible();

    // Verify VIEWER cannot run counterfactual simulation (UI disabled + backend 403)
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login/);
    await loginWithCredentials(page, viewerEmail, password);

    await page.goto(`/ghostpay/replay/${paymentIntentId}`);
    await expect(page.getByRole("heading", { name: /Provenance Timeline/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run Counterfactual" })).toBeDisabled();

    const simApiStatus = await page.evaluate(async (pid) => {
      const resp = await fetch(`/api/proxy/ghostpay/simulate/by-payment/${pid}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overrides: { per_tx_limit_minor: 5000 } }),
      });
      return resp.status;
    }, paymentIntentId);
    expect(simApiStatus).toBe(403);

    monitor.assertClean();
  });

  test("Journey 4: DisputeOS Case Lifecycle, Evidence, Provenance Graph, Analysis, Report, Approve, Synthetic Guard & Resolve", async ({
    page,
  }) => {
    const monitor = attachRuntimeMonitors(page);
    const id = uniqueId("dispute");

    await registerOrganization(page, {
      email: `owner-${id}@acme-e2e.internal`,
      password: "StrongPassword!123",
      fullName: "Dispute Owner",
      orgName: `Dispute Org ${id}`,
      orgSlug: `dispute-${id}`,
    });

    const { paymentIntentId } = await setupGuardianEntities(page, id);

    await page.goto("/disputes");
    await page.getByRole("button", { name: "+ New Dispute Case" }).click();
    await expect(page.getByRole("dialog", { name: "Open New Dispute Case" })).toBeVisible();

    await page.locator("#case-source-type").selectOption("SYNTHETIC_DEMO");
    await page.locator("#case-payment-intent").fill(paymentIntentId);
    await page.locator("#case-amount").fill("149.00");
    await page.locator("#case-reason").selectOption("MERCHANDISE_OR_SERVICES_NOT_RECEIVED");
    await page
      .locator("#case-claim")
      .fill("Customer claims cloud subscription access was never provisioned.");

    const createCasePromise = page.waitForResponse(
      (res) =>
        res.url().includes("/api/proxy/disputeos/cases") &&
        res.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Create Dispute Case" }).click();
    const createCaseJson = (await (await createCasePromise).json()) as { id: string };
    expect(createCaseJson.id).toBeTruthy();

    await page.goto(`/disputes/${createCaseJson.id}`);
    await expect(page.getByText("Evidence Records & Artifacts")).toBeVisible();

    // 1. Add structured JSON evidence
    await page.getByRole("button", { name: "+ Attach JSON Evidence" }).click();
    await page.locator("#json-ev-title").fill("Provisioning Access Log");
    await page.locator("#json-ev-type").selectOption("DELIVERY_RECEIPT");
    await page.locator("#json-ev-ref").fill(`log:${id}`);
    await page
      .locator("#json-ev-content")
      .fill(JSON.stringify({ provisioned: true, active_sessions: 4 }));
    await page.getByRole("button", { name: "Save Evidence Record" }).click();
    await expect(page.getByText("Provisioning Access Log")).toBeVisible();

    // 2. Upload file artifact
    await page.getByLabel("Artifact title").fill("Signed Delivery Receipt");
    await page.getByLabel("Evidence artifact file").setInputFiles({
      name: `receipt-${id}.txt`,
      mimeType: "text/plain",
      buffer: Buffer.from(`Delivery confirmed for case ${id}`),
    });
    await page.getByRole("button", { name: "Upload File Artifact" }).click();
    await expect(page.getByText("Signed Delivery Receipt")).toBeVisible();

    // 3. Run deterministic grounded analysis & inspect provenance graph / contradictions
    await page.getByRole("button", { name: "Run Grounded Analysis" }).click();
    await expect(page.getByText(/Evidence graph: \d+ nodes · \d+ edges/)).toBeVisible();
    await expect(
      page.getByText(/Deterministic Engine|LLM Augmented/),
    ).toBeVisible();

    // 4. Generate / Export report
    const reportPromise = page.waitForResponse(
      (res) =>
        res.url().includes(`/api/proxy/disputeos/cases/${createCaseJson.id}/report`) &&
        res.request().method() === "GET",
    );
    await page.getByRole("button", { name: "Export Report" }).click();
    const reportResp = await reportPromise;
    expect(reportResp.status()).toBe(200);

    // 5. Approve response draft
    const draftBox = page.locator("#draft-response");
    if (!(await draftBox.inputValue()).trim()) {
      await draftBox.fill("Verified provisioning logs confirm service delivery.");
    }
    await page.getByRole("button", { name: "Approve Draft for Submission" }).click();
    const approveDialog = page.locator("dialog[open]");
    await expect(approveDialog).toBeVisible();
    await approveDialog.getByRole("button", { name: "Approve Draft" }).click();
    await expect(approveDialog).toHaveCount(0);

    // 6. Verify synthetic case cannot be externally submitted
    const submitBtn = page.getByRole("button", { name: "Submit to PayPal" });
    await expect(submitBtn).toBeDisabled();
    await expect(submitBtn).toHaveAttribute(
      "title",
      "Synthetic demo cases cannot be submitted externally",
    );

    // 7. Resolve case
    await page.getByRole("button", { name: "Resolve Case" }).click();
    await expect(page.getByRole("dialog", { name: "Resolve Dispute Case" })).toBeVisible();
    await page.locator("#resolve-reason-input").fill("Resolved after E2E evidence review.");
    await page.getByRole("button", { name: "Confirm Resolution" }).click();
    await expect(page.getByText("RESOLVED").first()).toBeVisible();

    monitor.assertClean();
  });

  test("Journey 5: Developer Platform (API Keys, Webhooks, Deliveries), Settings (Billing & Privacy), Status & Legal", async ({
    page,
  }) => {
    const monitor = attachRuntimeMonitors(page);
    const id = uniqueId("dev");

    await registerOrganization(page, {
      email: `owner-${id}@acme-e2e.internal`,
      password: "StrongPassword!123",
      fullName: "Platform Owner",
      orgName: `Platform Org ${id}`,
      orgSlug: `dev-${id}`,
    });

    // 1. Developer Portal: API Key & Webhook Endpoint + Delivery History
    await page.goto("/developer");
    await page.locator("#key-name-input").fill(`e2e-runtime-key-${id}`);
    await page.locator("#key-role-select").selectOption("AGENT_SERVICE");
    await page.getByRole("button", { name: "Generate API Key" }).click();
    await expect(page.getByText(`e2e-runtime-key-${id}`)).toBeVisible();

    await page.getByRole("button", { name: /Webhooks & Logs/ }).click();
    await page.locator("#webhook-url-input").fill(`https://example.com/webhooks/${id}`);
    await page.locator("#webhook-desc-input").fill("E2E Webhook Listener");
    await page.getByRole("button", { name: "Add Webhook Endpoint" }).click();
    await expect(
      page.getByText(`https://example.com/webhooks/${id}`, { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: /Recent Webhook Deliveries/ })).toBeVisible();

    // 2. Settings: Billing & Quotas and Privacy Export / Erasure UI
    await page.goto("/settings");
    await page.getByRole("button", { name: "Stripe Billing & Quotas" }).click();
    await expect(page.getByRole("heading", { name: /Monthly Usage & Quotas/ })).toBeVisible();

    await page.getByRole("button", { name: "Data Privacy & GDPR/DPDPA" }).click();
    await expect(page.getByText("Data Subject Portability Export")).toBeVisible();
    await expect(page.getByRole("button", { name: "Request JSON Archive" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Request CSV Archive" })).toBeVisible();

    // 3. Public Status & Legal routes
    await page.goto("/status");
    await expect(page.getByRole("heading", { name: "All Systems Fully Operational" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Core Infrastructure Components" })).toBeVisible();

    await page.goto("/legal/terms");
    await expect(page.getByRole("heading", { name: "Master SaaS Terms of Service" })).toBeVisible();

    await page.goto("/legal/privacy");
    await expect(
      page.getByRole("heading", { name: "Global Privacy & Data Protection Policy" }),
    ).toBeVisible();

    await page.goto("/legal/dpa");
    await expect(page.getByRole("heading", { name: "Data Processing Addendum (DPA)" })).toBeVisible();

    monitor.assertClean();
  });
});
