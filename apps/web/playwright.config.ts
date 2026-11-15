import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  workers: 1,
  reporter: [["list"], ["html", {open:"never"}], ["json", {outputFile:"test-results/results.json"}]],
  use: { baseURL: process.env.E2E_BASE_URL || "http://localhost:3000", actionTimeout: 15000, trace: "retain-on-failure", channel: process.env.PLAYWRIGHT_CHANNEL || "chrome" },
  webServer: undefined,
});

