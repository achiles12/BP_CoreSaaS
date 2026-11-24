import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { makeMe, platformMe, staffMe } from "@/test/fixtures";
import { renderWithSession } from "@/test/render";

import { AppShell } from "./app-shell";
import { DevBanner } from "./dev-banner";
import { initials } from "./user-menu";

vi.mock("next/navigation", () => import("@/test/next-navigation"));

const nav = () => within(screen.getAllByRole("navigation", { name: "Main" })[0]!);

describe("AppShell", () => {
  it("shows the org name, user and permission-filtered nav", () => {
    renderWithSession(<AppShell me={makeMe()}>content</AppShell>, makeMe());
    expect(screen.getByTestId("org-name")).toHaveTextContent("Acme Inc");
    expect(screen.getByRole("button", { name: "User menu" })).toHaveTextContent("Ada Owner");
    // "Home" points at the user's own landing page (B09)
    expect(nav().getByRole("link", { name: "Home" })).toHaveAttribute("href", "/home/owner");
    expect(nav().getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("staff does not get the Users entry", () => {
    renderWithSession(<AppShell me={staffMe()}>x</AppShell>, staffMe());
    expect(nav().queryByText("Users")).not.toBeInTheDocument();
    expect(nav().getByText("Files")).toBeInTheDocument();
  });

  it("B10 pages are real links; Items shows only with items:read", () => {
    renderWithSession(<AppShell me={makeMe()}>x</AppShell>, makeMe());
    expect(nav().getByRole("link", { name: /Files/ })).toHaveAttribute("href", "/files");
    expect(nav().getByRole("link", { name: /Organization/ })).toHaveAttribute(
      "href",
      "/settings/organization",
    );
    expect(nav().queryByText("Items")).not.toBeInTheDocument();
    const withItems = makeMe({ permissions: [...makeMe().permissions, "items:read"] });
    renderWithSession(<AppShell me={withItems}>x</AppShell>, withItems);
    expect(screen.getAllByRole("link", { name: /Items/ })[0]).toHaveAttribute("href", "/items");
  });

  it("platform admin without org: 'Platform' label, Home and Platform links to /platform", () => {
    renderWithSession(<AppShell me={platformMe()}>x</AppShell>, platformMe());
    expect(screen.getByTestId("org-name")).toHaveTextContent("Platform");
    expect(nav().getByRole("link", { name: "Home" })).toHaveAttribute("href", "/platform");
    expect(nav().getByRole("link", { name: "Platform" })).toHaveAttribute("href", "/platform");
  });

  it("only the first matching entry is highlighted", async () => {
    const { setPathname } = await import("@/test/next-navigation");
    setPathname("/platform");
    renderWithSession(<AppShell me={platformMe()}>x</AppShell>, platformMe());
    expect(nav().getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(nav().getByRole("link", { name: "Platform" })).not.toHaveAttribute("aria-current");
    setPathname("/home");
  });

  it("verify banner only for unverified users", () => {
    renderWithSession(<AppShell me={makeMe()}>x</AppShell>, makeMe());
    expect(screen.queryByTestId("verify-banner")).not.toBeInTheDocument();
  });
});

describe("DevBanner", () => {
  it("shows in dev with the current host", () => {
    renderWithSession(<DevBanner env="dev" />);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Dev: emails go to Mailpit (localhost:8025)",
    );
  });
  it("hides outside dev", () => {
    renderWithSession(<DevBanner env="prod" />);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

describe("initials", () => {
  it.each([
    ["Ada Lovelace", "a@b.c", "AL"],
    ["Cher", "a@b.c", "C"],
    [null, "zed@b.c", "Z"],
    ["  ", "x@b.c", "X"],
  ])("%s / %s -> %s", (n, e, out) => expect(initials(n, e)).toBe(out));
});
