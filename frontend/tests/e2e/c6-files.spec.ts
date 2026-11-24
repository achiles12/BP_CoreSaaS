// C6: file upload → list → search → download → delete (critical_user_flow C6).
import { readFileSync, writeFileSync } from "node:fs";

import { test } from "@playwright/test";

import { expect, loginAs, logout } from "./helpers";

test("C6 staff uploads, everyone finds and downloads it, user cannot change it, manager deletes", async ({
  page,
}) => {
  const tag = `ezsix${Date.now().toString(36)}`;
  const name = `${tag}-report.pdf`;
  const body = Buffer.from(`%PDF-1.4\n% e2e ${tag}\n`);
  const path = `/tmp/${name}`;
  writeFileSync(path, body);

  // staff uploads
  await loginAs(page, "staff");
  await page.goto("/files");
  await page.getByRole("button", { name: "Upload" }).first().click();
  await page.getByLabel("Choose files").setInputFiles(path);
  await expect(page.getByRole("dialog").getByText("Done", { exact: true }).first()).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("row", { name: new RegExp(name) })).toBeVisible();

  // too large / wrong type is refused before anything is stored
  writeFileSync("/tmp/notes.md", "# no browser MIME type\n");
  await page.getByRole("button", { name: "Upload" }).first().click();
  await page.getByLabel("Choose files").setInputFiles("/tmp/notes.md");
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("not allowed");
  await page.keyboard.press("Escape");
  await logout(page);

  // user: finds it with search, downloads the same bytes, cannot upload or delete
  await loginAs(page, "user");
  await page.goto(`/search?q=${tag}`);
  await expect(page.getByTestId("search-results")).toContainText(name);
  const [dl] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: new RegExp(name) }).click(),
  ]);
  expect(dl.suggestedFilename()).toBe(name);
  expect(readFileSync(await dl.path())).toEqual(body);
  await page.goto(`/files?q=${tag}`);
  await expect(page.getByRole("row", { name: new RegExp(name) })).toBeVisible();
  expect(await page.getByRole("button", { name: "Upload" }).count()).toBe(0);
  await page.getByRole("button", { name: `Actions for ${name}` }).click();
  expect(await page.getByRole("menuitem", { name: "Delete" }).count()).toBe(0);
  await page.keyboard.press("Escape");
  await logout(page);

  // manager deletes; it leaves the list
  await loginAs(page, "manager");
  await page.goto(`/files?q=${tag}`);
  await page.getByRole("button", { name: `Actions for ${name}` }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("No files match these filters.")).toBeVisible();
});
