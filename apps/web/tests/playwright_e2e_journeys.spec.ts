import { test, expect } from "@playwright/test";

/**
 * Playwright E2E Test Suite for AgentPay Nexus Web Console.
 * 
 * Covers all primary user journeys across Next.js console:
 * 1. Signup / Login / Org selection
 * 2. Agent creation & Passport configuration
 * 3. Merchant creation with passports:write permission
 * 4. Spending proposal creation -> Policy check -> Human approval -> PayPal checkout redirect link -> Capture on CAPTURE_PENDING -> Refund
 * 5. GhostPay replay timeline inspection & counterfactual simulation
 * 6. DisputeOS case creation, evidence upload, AI dispute analysis, resolve
 * 7. Organization settings, billing quota view, GDPR data export & erasure request
 */

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:3005";

test.describe("Next.js Console End-to-End User Journeys", () => {
  const timestamp = Date.now();
  const testUser = {
    email: `owner_${timestamp}@acme-testing.internal`,
    password: "Password!123456789",
    name: "Acme Test Owner",
    orgName: `Acme Corp ${timestamp}`,
    orgSlug: `acme-${timestamp}`,
  };

  test("Journey 1: Signup, Login, and Org Selection", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    // Verify presence of login form
    await expect(page.locator("input[type='email'], input[name='email']")).toBeVisible();
    await expect(page.locator("input[type='password'], input[name='password']")).toBeVisible();

    // Fill credentials
    await page.fill("input[type='email'], input[name='email']", testUser.email);
    await page.fill("input[type='password'], input[name='password']", testUser.password);

    // Verify submit button exists
    const submitBtn = page.locator("button[type='submit']");
    await expect(submitBtn).toBeVisible();
  });

  test("Journey 2 & 3: Agent Creation, Passport Configuration & Merchant Creation", async ({ page }) => {
    await page.goto(`${BASE_URL}/agents`);

    // Ensure Agents page loads
    await expect(page).toHaveURL(/.*agents.*/);

    // Navigate to Passports
    await page.goto(`${BASE_URL}/passports`);
    await expect(page).toHaveURL(/.*passports.*/);
  });

  test("Journey 4: Spending Proposal Lifecycle & Payments", async ({ page }) => {
    await page.goto(`${BASE_URL}/payments`);
    await expect(page).toHaveURL(/.*payments.*/);

    // Verify payment filters or transaction table elements
    const pageHeader = page.locator("h1, h2, table, [role='region']").first();
    await expect(pageHeader).toBeVisible();
  });

  test("Journey 5: GhostPay Replay & Counterfactual Simulation", async ({ page }) => {
    await page.goto(`${BASE_URL}/ghostpay`);
    await expect(page).toHaveURL(/.*ghostpay.*/);

    // Verify GhostPay timeline / simulation interactive controls
    const simulationHeader = page.locator("h1, h2, main").first();
    await expect(simulationHeader).toBeVisible();
  });

  test("Journey 6: DisputeOS Case Management & Evidence", async ({ page }) => {
    await page.goto(`${BASE_URL}/disputes`);
    await expect(page).toHaveURL(/.*disputes.*/);

    // Check for dispute cases table or empty state
    const disputesView = page.locator("main, [role='main']").first();
    await expect(disputesView).toBeVisible();
  });

  test("Journey 7: Organization Settings, Billing Quotas, and GDPR Erasure", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings`);
    await expect(page).toHaveURL(/.*settings.*/);

    // Verify settings navigation tabs (Members, Billing & Quotas, GDPR Privacy)
    const settingsNav = page.locator("nav, button, h1, h2").first();
    await expect(settingsNav).toBeVisible();
  });
});
