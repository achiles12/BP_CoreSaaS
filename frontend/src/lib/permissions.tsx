"use client";
// Permission helpers (B08 D9, object 6). UX only: the backend enforces every
// permission with require(<key>) and answers 403 regardless of what the UI
// shows.
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import type { MeOut } from "@/api/generated/model";

import { useSession } from "./auth";

type Who = Pick<MeOut, "permissions" | "is_platform_admin"> | null | undefined;

/** True when the user holds `perm`. No session -> false. */
export function can(me: Who, perm: string): boolean {
  return !!me && me.permissions.includes(perm);
}

/** True when the user holds at least one of `perms` (empty list -> true). */
export function canAny(me: Who, perms: string[]): boolean {
  return perms.length === 0 || perms.some((p) => can(me, p));
}

/** Anything filterable by permission (navigation entries, actions...). */
export interface Gated {
  permission?: string;
  platformAdmin?: boolean;
}

/**
 * Keep the entries this user may see:
 *  - `platformAdmin` entries: platform admins only
 *  - `permission` entries: users holding that permission
 *  - neither: everyone signed in
 */
export function filterNav<T extends Gated>(items: T[], me: Who): T[] {
  if (!me) return [];
  return items.filter((item) => {
    if (item.platformAdmin) return me.is_platform_admin;
    if (item.permission) return can(me, item.permission);
    return true;
  });
}

/** Render `children` only when the user holds `perm`, else `fallback`. */
export function Can({
  perm,
  children,
  fallback = null,
}: {
  perm: string;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { me } = useSession();
  return <>{can(me, perm) ? children : fallback}</>;
}

/**
 * Page-level guard: once the session is loaded and `perm` is missing, send
 * the user to /403 (ui_screens.md §3). Renders nothing until allowed.
 */
export function RequirePermission({ perm, children }: { perm: string; children: ReactNode }) {
  const { me, isLoading } = useSession();
  const router = useRouter();
  const allowed = can(me, perm);
  useEffect(() => {
    if (!isLoading && me && !allowed) router.replace("/403");
  }, [isLoading, me, allowed, router]);
  return allowed ? <>{children}</> : null;
}
