// Current organization slug for the X-Tenant header (B08 D8).
//
// One user = one org (B04 D1), so the slug simply comes from /me.org.slug.
// It is held in memory (read synchronously by the fetcher on every call) and
// mirrored to localStorage["last_org"] so a reload knows it before /me
// returns. login/logout call clearOrg() so a slug left behind by another
// account on the same browser is never sent. Storage can be unavailable
// (private mode, blocked site data), so every access is wrapped.
import { log } from "./log";

export const LAST_ORG_KEY = "last_org";

let current: string | null | undefined; // undefined = not read from storage yet

function readStorage(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(LAST_ORG_KEY);
  } catch (err) {
    log.warn("org.storage_read_failed", { err: String(err) });
    return null;
  }
}

/** Slug to send as X-Tenant, or null (no org / platform admin). */
export function getOrg(): string | null {
  if (current === undefined) current = readStorage();
  return current;
}

export function setOrg(slug: string | null): void {
  current = slug;
  try {
    if (slug) window.localStorage.setItem(LAST_ORG_KEY, slug);
    else window.localStorage.removeItem(LAST_ORG_KEY);
  } catch (err) {
    log.warn("org.storage_write_failed", { err: String(err) });
  }
}

export function clearOrg(): void {
  setOrg(null);
}

/** Test hook: forget the in-memory value so the next getOrg() re-reads storage. */
export function _resetOrgForTests(): void {
  current = undefined;
}
