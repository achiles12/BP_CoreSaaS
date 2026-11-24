import { describe, expect, it } from "vitest";

import { isLandingPath, ownLanding, resolvePostLogin } from "./landing";

const owner = { landing_path: "/home/owner" };
const noOrg = { landing_path: null };

describe("landing helpers", () => {
  it("isLandingPath", () => {
    expect(isLandingPath("/home/staff")).toBe(true);
    expect(isLandingPath("/home/whatever?x=1")).toBe(true);
    expect(isLandingPath("/platform")).toBe(true);
    expect(isLandingPath("/home")).toBe(true);
    expect(isLandingPath("/users")).toBe(false);
    expect(isLandingPath("/home/a/b")).toBe(false);
  });

  it("ownLanding falls back to /no-organization", () => {
    expect(ownLanding(owner)).toBe("/home/owner");
    expect(ownLanding(noOrg)).toBe("/no-organization");
  });

  it.each([
    [null, "/home/owner"],
    ["/users?page=2", "/users?page=2"], // deep link wins
    ["/home/staff", "/home/owner"], // another role's landing page: own instead
    ["/platform", "/home/owner"],
    ["/post-login?next=/x", "/home/owner"],
    ["https://evil.com", "/home/owner"],
    ["/login", "/home/owner"],
  ])("resolvePostLogin(owner, %s) -> %s", (next, out) => {
    expect(resolvePostLogin(owner, next)).toBe(out);
  });

  it("resolvePostLogin without org", () => {
    expect(resolvePostLogin(noOrg, null)).toBe("/no-organization");
  });
});
