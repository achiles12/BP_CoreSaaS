// C1: login → role landing page, for every role (critical_user_flow C1).
import { test } from "@playwright/test";

import { ACCOUNTS, expect, loginAs, logout, me, sidebar, type Role } from "./helpers";

// Sidebar entries and the permission that shows them (config/navigation.ts).
const NAV: [string, string | null][] = [
  ["Home", null],
  ["Files", "files:read"],
  ["Search", "search:use"],
  ["Users", "users:read"],
  ["Organization", "org:read"],
  ["Items", "items:read"],
  ["Platform", "platform"],
];

for (const role of Object.keys(ACCOUNTS) as Role[]) {
  test(`C1 ${role}: lands on ${ACCOUNTS[role].landing}, sidebar by permission, guards, logout`, async ({
    page,
  }) => {
    await loginAs(page, role);
    await expect(page.getByTestId("landing-title")).toBeVisible();

    const m = await me(page);
    const want = NAV.filter(([, p]) =>
      p === "platform" ? m.is_platform_admin : !p || m.permissions.includes(p),
    ).map(([l]) => l);
    expect(await sidebar(page)).toEqual(want);

    // another role's landing page sends you back to your own
    const other = role === "owner" ? "/home/staff" : "/home/owner";
    await page.goto(other);
    await page.waitForURL(`**${ACCOUNTS[role].landing}`);

    // logout clears the session; Back shows no data
    await logout(page);
    await page.goBack();
    await page.waitForTimeout(1000);
    expect(await page.getByTestId("landing-title").count()).toBe(0);
    await page.goto(ACCOUNTS[role].landing);
    await page.waitForURL(/\/login\?next=/);
  });
}
