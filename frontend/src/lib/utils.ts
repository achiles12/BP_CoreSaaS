import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class names; later classes win (shadcn/ui helper). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Return `next` only if it is a same-site relative path ("/home?x=1"), else
 * `fallback`. Blocks open redirects such as "//evil.com" or "https://...".
 */
export function safeNext(next: string | null | undefined, fallback = "/home"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return fallback;
  }
  // Never bounce back to the login page itself.
  if (next === "/login" || next.startsWith("/login?")) return fallback;
  return next;
}
