import { expect, Page } from "@playwright/test";

// The whole isolated suite shares one client IP. Respect the real login limiter
// instead of relaxing it or resetting server security state between workflows.
export async function login(page: Page, email: string, password: string, expectedStatus = 200) {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await expect.poll(async () => {
    const received = page.waitForResponse(r => r.url().endsWith("/api/v1/auth/login") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Sign in to workspace" }).click();
    const response = await received;
    expect([expectedStatus, 429], await response.text()).toContain(response.status());
    return response.status();
  }, { timeout: 65000, intervals: [5000] }).toBe(expectedStatus);
  if (expectedStatus === 200) await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
}

// Full-page evidence screenshots: from the top, with the sticky banner, top bar and sidebar laid out
// in normal flow, so the capture matches what a person sees instead of freezing them mid-page.
export async function fullShot(page: Page, path: string) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path, fullPage: true, style: ".research-banner,.topbar{position:static!important}.sidebar{position:static!important;height:auto!important}" });
}
