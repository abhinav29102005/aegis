import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const BASE_URL = process.env.BASE_URL || "https://aegis-staging.abhinavkumarsingh.tech";
const SCREENSHOT_DIR = "/home/bigboyaks/.gemini/antigravity/brain/deb83551-cbad-4208-9a0c-58939ea945f5/screenshots";

async function runDemo() {
  console.log(`Starting Live Staging Demo Tour on ${BASE_URL}...`);
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  });

  const page = await context.newPage();

  // 1. Visit Login
  console.log("\n[1/7] Navigating to Login...");
  await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle", timeout: 20000 });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "01_login_page.png"), fullPage: true });
  console.log("  Saved: 01_login_page.png");

  // 2. Perform Login
  console.log("\n[2/7] Logging in as Chief Auditor...");
  await page.fill('input[type="email"]', "chief-auditor-bf1ab00d@aegis-nexus.tech");
  await page.fill('input[type="password"]', "SuperSecurePassword123!@#");
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15000 }),
    page.click('button[type="submit"]')
  ]);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1000);
  console.log(`  Redirected to: ${page.url()}`);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "02_dashboard_overview.png"), fullPage: true });
  console.log("  Saved: 02_dashboard_overview.png");

  // 3. Visit Agents & Spending Passports
  console.log("\n[3/7] Navigating to Agents & Spending Passports...");
  await page.goto(`${BASE_URL}/agents`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "03_agents_passports.png"), fullPage: true });
  console.log("  Saved: 03_agents_passports.png");

  // 4. Visit Payments & Checkouts
  console.log("\n[4/7] Navigating to Payments & Authorizations...");
  await page.goto(`${BASE_URL}/payments`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "04_payments_authorizations.png"), fullPage: true });
  console.log("  Saved: 04_payments_authorizations.png");

  // 5. Visit GhostPay Forensics
  console.log("\n[5/7] Navigating to GhostPay Forensics...");
  await page.goto(`${BASE_URL}/ghostpay`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "05_ghostpay_forensics.png"), fullPage: true });
  console.log("  Saved: 05_ghostpay_forensics.png");

  // 6. Visit DisputeOS
  console.log("\n[6/7] Navigating to DisputeOS Case Management...");
  await page.goto(`${BASE_URL}/disputes`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "06_disputeos_cases.png"), fullPage: true });
  console.log("  Saved: 06_disputeos_cases.png");

  // 7. Visit Developer & API Keys
  console.log("\n[7/7] Navigating to Developer Settings & System Status...");
  await page.goto(`${BASE_URL}/developer`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "07_developer_settings.png"), fullPage: true });
  console.log("  Saved: 07_developer_settings.png");

  await page.goto(`${BASE_URL}/status`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "08_system_status.png"), fullPage: true });
  console.log("  Saved: 08_system_status.png");

  await browser.close();
  console.log("\n✓ All 8 high-resolution screenshots captured successfully!");
}

runDemo().catch((err) => {
  console.error("Demo run error:", err);
  process.exit(1);
});
