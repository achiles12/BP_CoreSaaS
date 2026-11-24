// Form helpers shared by the public auth pages (B09 D1, ui_screens.md §4).
// Rules mirror the backend so most mistakes are caught before a round trip;
// the backend stays the authority (its 422 fields are mapped back on).
import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { z } from "zod";

import { isApiError } from "./api-error";

/** Backend MIN_PASSWORD_LEN (core/security.py). */
export const MIN_PASSWORD_LEN = 12;
export const MAX_PASSWORD_LEN = 128;

export const PASSWORD_HINT = `At least ${MIN_PASSWORD_LEN} characters, with letters and numbers.`;

export const emailField = z
  .string()
  .trim()
  .toLowerCase()
  .min(1, "Enter your email")
  .pipe(z.email("Enter a valid email address"));

export const newPasswordField = z
  .string()
  .min(MIN_PASSWORD_LEN, `Use at least ${MIN_PASSWORD_LEN} characters`)
  .max(MAX_PASSWORD_LEN, `Use at most ${MAX_PASSWORD_LEN} characters`)
  .regex(/[A-Za-z]/, "Include at least one letter")
  .regex(/\d/, "Include at least one number");

/** Adds the "confirm" rule: must equal `password` (error shown on confirm). */
export function passwordsMatch<T extends { password: string; confirm: string }>(v: T) {
  return v.password === v.confirm;
}
export const CONFIRM_MISMATCH = { message: "Passwords do not match", path: ["confirm"] };

/**
 * Put a server 422 `error.fields` list onto the form. The last `loc` segment
 * is the backend field name; `fieldMap` renames it to the form field
 * (e.g. new_password -> password). Returns a form-level message for anything
 * that is not field-specific, or null when everything was mapped.
 */
export function applyServerErrors<T extends FieldValues>(
  err: unknown,
  setError: UseFormSetError<T>,
  fieldMap: Record<string, Path<T>> = {},
  known: Path<T>[] = [],
): string | null {
  if (!isApiError(err)) return "Something went wrong. Please try again.";
  if (err.status === 0) return "Cannot reach the server. Check your connection.";
  if (err.status === 429) {
    return err.retryAfter
      ? `Too many attempts. Try again in ${err.retryAfter} s.`
      : "Too many attempts. Try again in a minute.";
  }
  if (err.status === 422 && err.fields?.length) {
    let unmapped = false;
    for (const f of err.fields) {
      const raw = String(f.loc[f.loc.length - 1] ?? "");
      const name = (fieldMap[raw] ?? raw) as Path<T>;
      if (known.includes(name)) setError(name, { type: "server", message: capitalize(f.msg) });
      else unmapped = true;
    }
    return unmapped ? err.message : null;
  }
  return err.message;
}

function capitalize(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}
