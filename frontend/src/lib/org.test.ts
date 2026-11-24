import { beforeEach, describe, expect, it, vi } from "vitest";

import { _resetOrgForTests, clearOrg, getOrg, LAST_ORG_KEY, setOrg } from "./org";

beforeEach(() => _resetOrgForTests());

describe("org state", () => {
  it("mirrors the slug to localStorage and clears it", () => {
    setOrg("acme");
    expect(getOrg()).toBe("acme");
    expect(localStorage.getItem(LAST_ORG_KEY)).toBe("acme");
    clearOrg();
    expect(getOrg()).toBeNull();
    expect(localStorage.getItem(LAST_ORG_KEY)).toBeNull();
  });

  it("reads a stored slug after a reload", () => {
    localStorage.setItem(LAST_ORG_KEY, "beta");
    expect(getOrg()).toBe("beta");
  });

  it("survives storage that throws (private mode)", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(getOrg()).toBeNull();
    expect(() => setOrg("acme")).not.toThrow();
    expect(getOrg()).toBe("acme"); // memory still works
  });
});
