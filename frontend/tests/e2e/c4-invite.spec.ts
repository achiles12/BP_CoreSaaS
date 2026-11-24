// C4: invite → accept → login (critical_user_flow C4).
import { test } from "@playwright/test";

import { expect, login, loginAs, mailLink, PASSWORD } from "./helpers";

test("C4 owner invites a staff member, who accepts and lands on /home/staff", async ({
  page,
  browser,
}) => {
  const email = `e2e-inv-${Date.now()}@e2e.test`;
  const since = Date.now();

  await loginAs(page, "owner");
  await page.goto("/users");
  await page.getByRole("button", { name: "Invite" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByLabel("Role").selectOption("staff");
  await dialog.getByRole("button", { name: "Send invite" }).click();
  await expect(dialog).toBeHidden();
  await page.getByRole("tab", { name: /Pending invitations/ }).click();
  await expect(page.getByRole("row", { name: new RegExp(email) })).toBeVisible();

  // the invitee, in a fresh browser (no owner cookies)
  const link = await mailLink(email, "/accept-invite?token=", since);
  const ctx = await browser.newContext();
  const invitee = await ctx.newPage();
  await invitee.goto(link);
  await invitee.getByLabel("Full name").fill("E2E Invitee");
  await invitee.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await invitee.getByLabel("Confirm password").fill(PASSWORD);
  await invitee.getByRole("button", { name: "Create account and join" }).click();
  // Accepting shows a confirmation with a Log in button (no automatic redirect).
  await expect(invitee.getByText("You joined E2E Org")).toBeVisible();
  await invitee.getByRole("link", { name: "Log in" }).click();
  await invitee.waitForURL(/\/login/);

  await login(invitee, email);
  await invitee.waitForURL("**/home/staff");
  await expect(invitee.getByTestId("landing-title")).toHaveText("Staff home");

  // the token cannot be used twice
  await invitee.goto(link);
  await expect(
    invitee.getByText("This invitation link is invalid, expired or already used."),
  ).toBeVisible();
  await ctx.close();
});
