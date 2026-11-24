"use client";
// Page frame for (app) pages (B10): permission gate + title row with actions.
// The (app) layout only renders pages once /me has loaded, so `me` is set.
import type { ReactNode } from "react";

import type { MeOut } from "@/api/generated/model";
import { useSession } from "@/lib/auth";
import { RequirePermission } from "@/lib/permissions";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  actions,
  children,
}: {
  title: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="page-title">
          {title}
        </h1>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children && <p className="text-muted-foreground text-sm">{children}</p>}
    </div>
  );
}

/**
 * Renders `children(me)` once the user holds `perm` (else /403, ui_screens §3).
 * Without `perm` any signed-in user may see the page.
 */
export function GatedPage({
  perm,
  wide = false,
  children,
}: {
  perm?: string;
  wide?: boolean;
  children: (me: MeOut) => ReactNode;
}) {
  const { me } = useSession();
  if (!me) return null;
  const body = (
    <div className={cn("mx-auto space-y-6", wide ? "max-w-6xl" : "max-w-3xl")}>{children(me)}</div>
  );
  return perm ? <RequirePermission perm={perm}>{body}</RequirePermission> : body;
}
