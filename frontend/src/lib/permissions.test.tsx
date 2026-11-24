import { describe, expect, it } from "vitest";

import { NAVIGATION } from "@/config/navigation";
import { makeMe, platformMe, staffMe } from "@/test/fixtures";

import { can, canAny, filterNav } from "./permissions";

const labels = (me: Parameters<typeof filterNav>[1]) =>
  filterNav(NAVIGATION, me).map((i) => i.label);

describe("permissions", () => {
  it("can / canAny", () => {
    const me = staffMe();
    expect(can(me, "files:read")).toBe(true);
    expect(can(me, "users:read")).toBe(false);
    expect(can(null, "files:read")).toBe(false);
    expect(canAny(me, ["users:read", "org:read"])).toBe(true);
    expect(canAny(me, [])).toBe(true);
  });

  it("owner sees every tenant entry but not Platform", () => {
    expect(labels(makeMe())).toEqual(["Home", "Files", "Search", "Users", "Organization"]);
  });

  it("staff does not see Users", () => {
    expect(labels(staffMe())).toEqual(["Home", "Files", "Search", "Organization"]);
  });

  it("platform admin without org sees Home and Platform only", () => {
    expect(labels(platformMe())).toEqual(["Home", "Platform"]);
  });

  it("no session -> nothing", () => {
    expect(labels(undefined)).toEqual([]);
  });
});
