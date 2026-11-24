// C5: password reset (critical_user_flow C5). Uses reset@e2e.test only.
import { test } from "@playwright/test";

import { expect, login, mailLink, PASSWORD } from "./helpers";

const EMAIL = "reset@e2e.test"; // seed_e2e.py resets its password every run
const FORGOT_SENT = "If an account exists for that address, we sent a password reset link.";

test("C5 reset: same answer for unknown email; link resets; old password stops working", async ({
  page,
}) => {
  // unknown and known email get the identical message
  for (const email of [`nobody-${Date.now()}@e2e.test`, EMAIL]) {
    await page.goto("/forgot-password");
    await page.getByLabel("Email").fill(email);
    const since = Date.now();
    await page.getByRole("button", { name: "Send reset link" }).click();
    await expect(page.getByText(FORGOT_SENT)).toBeVisible();
    if (email === EMAIL) {
      const link = await mailLink(EMAIL, "/reset-password?token=", since);
      const fresh = `E2e-new-${Date.now()}x`;
      await page.goto(link);
      await page.getByLabel("New password", { exact: true }).fill(fresh);
      await page.getByLabel("Confirm new password").fill(fresh);
      await page.getByRole("button", { name: "Change password" }).click();
      await expect(page.getByText(/password (was )?changed|Go to log in/i).first()).toBeVisible();

      // old password fails, new one works
      await login(page, EMAIL, PASSWORD);
      await expect(page.locator("form [role=alert]")).toContainText("Invalid email or password");
      await login(page, EMAIL, fresh);
      await page.waitForURL("**/home/user");

      // the link cannot be used twice: the form only checks the token on submit
      await page.goto(link);
      await page.getByLabel("New password", { exact: true }).fill(`${fresh}2`);
      await page.getByLabel("Confirm new password").fill(`${fresh}2`);
      await page.getByRole("button", { name: "Change password" }).click();
      await expect(page.getByText("This reset link is invalid or has expired.")).toBeVisible();
    }
  }
});
