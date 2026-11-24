// Labelled input with an accessible error message (ui_screens.md §6:
// labelled inputs; the error is linked via aria-describedby).
import type { ComponentProps, ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function FormField({
  id,
  label,
  error,
  hint,
  ...input
}: { id: string; label: string; error?: string; hint?: ReactNode } & ComponentProps<typeof Input>) {
  const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...input}
      />
      {hint && !error && (
        <p id={`${id}-hint`} className="text-muted-foreground text-xs">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}

/** Form-level error banner. */
export function FormAlert({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm"
    >
      {message}
    </div>
  );
}
