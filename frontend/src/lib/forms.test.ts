import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError } from "./api-error";
import {
  applyServerErrors,
  CONFIRM_MISMATCH,
  emailField,
  newPasswordField,
  passwordsMatch,
} from "./forms";

describe("form schemas", () => {
  it("emailField trims and lower-cases", () => {
    expect(emailField.parse("  Ada@Example.COM ")).toBe("ada@example.com");
    expect(emailField.safeParse("nope").success).toBe(false);
  });

  it.each([
    ["short1", false],
    ["onlylettersxxxx", false],
    ["123456789012", false],
    ["goodpassword12", true],
  ])("newPasswordField(%s) -> %s", (pw, ok) => {
    expect(newPasswordField.safeParse(pw).success).toBe(ok);
  });

  it("confirm must match", () => {
    const s = z
      .object({ password: z.string(), confirm: z.string() })
      .refine(passwordsMatch, CONFIRM_MISMATCH);
    const r = s.safeParse({ password: "a", confirm: "b" });
    expect(r.success).toBe(false);
    expect(r.error?.issues[0]?.path).toEqual(["confirm"]);
  });
});

describe("applyServerErrors", () => {
  it("maps 422 fields onto form fields (with renames)", () => {
    const setError = vi.fn();
    const err = new ApiError({
      status: 422,
      code: "validation_error",
      message: "weak",
      fields: [{ loc: ["body", "new_password"], msg: "password must contain letters and numbers" }],
    });
    expect(applyServerErrors(err, setError, { new_password: "password" }, ["password"])).toBeNull();
    expect(setError).toHaveBeenCalledWith("password", {
      type: "server",
      message: "Password must contain letters and numbers",
    });
  });

  it("unmapped fields fall back to a form message", () => {
    const err = new ApiError({
      status: 422,
      code: "v",
      message: "Request validation failed",
      fields: [{ loc: ["body", "x"], msg: "bad" }],
    });
    expect(applyServerErrors(err, vi.fn(), {}, ["password"])).toBe("Request validation failed");
  });

  it("429, network and other errors", () => {
    expect(
      applyServerErrors(
        new ApiError({ status: 429, code: "r", message: "", retryAfter: 9 }),
        vi.fn(),
      ),
    ).toMatch(/9 s/);
    expect(applyServerErrors(new ApiError({ status: 0, code: "n", message: "" }), vi.fn())).toMatch(
      /Cannot reach/,
    );
    expect(
      applyServerErrors(
        new ApiError({ status: 409, code: "c", message: "Already member" }),
        vi.fn(),
      ),
    ).toBe("Already member");
    expect(applyServerErrors(new Error("x"), vi.fn())).toMatch(/Something went wrong/);
  });
});
