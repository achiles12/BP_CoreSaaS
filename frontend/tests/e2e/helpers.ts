// Shared helpers for the critical-flow specs (B12 §3.2).
import { expect, type Page } from "@playwright/test";

export const PASSWORD = "E2e-pass-2026-ok"; // seed_e2e.py
export const MAILPIT = process.env.MAILPIT ?? "http://localhost:8025";

/** The e2e tenant's accounts (seeded fresh before every run). */
export const ACCOUNTS = {
  platform: { email: "e2e-platform@e2e.test", landing: "/platform" },
  owner: { email: "owner@e2e.test", landing: "/home/owner" },
  admin: { email: "admin@e2e.test", landing: "/home/admin" },
  manager: { email: "manager@e2e.test", landing: "/home/manager" },
  staff: { email: "staff@e2e.test", landing: "/home/staff" },
  user: { email: "user@e2e.test", landing: "/home/user" },
} as const;
export type Role = keyof typeof ACCOUNTS;

export async function login(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
}

export async function loginAs(page: Page, role: Role): Promise<void> {
  await login(page, ACCOUNTS[role].email);
  await page.waitForURL(`**${ACCOUNTS[role].landing}`);
}

export async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "User menu" }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await page.waitForURL(/\/login/);
}

/** /me as the page sees it (cookies of the page's context). */
export async function me(
  page: Page,
): Promise<{ permissions: string[]; is_platform_admin: boolean }> {
  return page.evaluate(() => fetch("/api/me").then((r) => r.json()));
}

/**
 * Newest Mailpit message to `to` received after `since`, whose text holds a
 * link containing `marker` (e.g. "/accept-invite?token="). Polls up to 30 s.
 */
export async function mailLink(to: string, marker: string, since: number): Promise<string> {
  const re = new RegExp(`https?://\\S*${marker.replace(/[?]/g, "\\?")}[A-Za-z0-9_-]+`);
  for (let i = 0; i < 60; i++) {
    const res = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`);
    const list = ((await res.json()).messages ?? []) as { ID: string; Created: string }[];
    for (const m of list) {
      if (Date.parse(m.Created) < since - 2000) continue;
      const full = await (await fetch(`${MAILPIT}/api/v1/message/${m.ID}`)).json();
      const hit = (full.Text as string).match(re);
      if (hit) return hit[0];
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`no mail to ${to} with ${marker}`);
}

/** Sidebar labels as shown (without "soon" badges). */
export async function sidebar(page: Page): Promise<string[]> {
  const text = await page.getByRole("navigation", { name: "Main" }).first().innerText();
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export { expect };
