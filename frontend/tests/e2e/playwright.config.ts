// Playwright config for the critical-flow suite (B12 D8).
// BASE = the frontend as the email links point to it (FRONTEND_URL), so a link
// from Mailpit opens on the same origin the test logged in on.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: /c\d-.*\.spec\.ts/,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  workers: 1, // one shared tenant (e2e); specs change its state
  retries: 0,
  outputDir: process.env.E2E_OUT ? `${process.env.E2E_OUT}/artifacts` : "test-results",
  reporter: [
    ["list"],
    ["junit", { outputFile: `${process.env.E2E_OUT ?? "."}/junit.xml` }],
    ["html", { outputFolder: `${process.env.E2E_OUT ?? "."}/html`, open: "never" }],
  ],
  use: {
    baseURL: process.env.BASE ?? "http://localhost:3200",
    viewport: { width: 1280, height: 860 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
