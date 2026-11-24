// Where a signed-in user belongs (B09 D3/D4, ui_screens.md S05/S07).
import type { MeOut } from "@/api/generated/model";

import { safeNext } from "./utils";

/** Roles with a /home/<role> landing page (seeded in B02, landing paths in B04). */
export const ROLE_KEYS = ["owner", "admin", "manager", "staff", "user"] as const;
export type RoleKey = (typeof ROLE_KEYS)[number];

export const PLATFORM_PATH = "/platform";
export const NO_ORG_PATH = "/no-organization";
export const POST_LOGIN_PATH = "/post-login";
/** Sidebar "Home" placeholder href, resolved to the user's own landing page. */
export const HOME_HREF = "/home";

export function isRoleKey(v: string): v is RoleKey {
  return (ROLE_KEYS as readonly string[]).includes(v);
}

/** True for /home/<role> (any role) and /platform, with or without a query. */
export function isLandingPath(path: string): boolean {
  const p = path.split("?")[0]!.replace(/\/+$/, "");
  return p === PLATFORM_PATH || p === "/home" || /^\/home\/[^/]+$/.test(p);
}

/** The user's own landing page; /no-organization when the backend has none (B04 D15). */
export function ownLanding(me: Pick<MeOut, "landing_path">): string {
  return me.landing_path ?? NO_ORG_PATH;
}

/**
 * Post-login target (D3): a safe `next` wins unless it is a landing page
 * (another role's page would only bounce, and the user's own page is the
 * default anyway) or the post-login page itself.
 */
export function resolvePostLogin(me: Pick<MeOut, "landing_path">, next?: string | null): string {
  const own = ownLanding(me);
  const target = safeNext(next, own);
  if (target === own) return own;
  if (isLandingPath(target) || target.startsWith(POST_LOGIN_PATH)) return own;
  return target;
}
