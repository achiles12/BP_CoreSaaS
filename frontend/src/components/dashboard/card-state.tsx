"use client";
// Shared loading / error rendering for cards that fetch (B09 D5).
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api-error";

export function CardLoading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  );
}

/** 403 email_not_verified gets its own hint (B03 D1: tenant data needs a verified email). */
export function CardError({ error }: { error: unknown }): ReactNode {
  const text =
    isApiError(error) && error.code === "email_not_verified"
      ? "Verify your email to see this."
      : isApiError(error)
        ? error.message
        : "Could not load.";
  return <p className="text-muted-foreground text-sm">{text}</p>;
}
