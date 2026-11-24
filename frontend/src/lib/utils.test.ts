import { describe, expect, it } from "vitest";

import { safeNext } from "./utils";

describe("safeNext", () => {
  it.each([
    ["/home", "/home"],
    ["/users?page=2", "/users?page=2"],
    [null, "/home"],
    ["", "/home"],
    ["https://evil.com", "/home"],
    ["//evil.com", "/home"],
    ["/\\evil.com", "/home"],
    ["/login", "/home"],
    ["/login?next=/x", "/home"],
  ])("%s -> %s", (input, out) => expect(safeNext(input)).toBe(out));
});
