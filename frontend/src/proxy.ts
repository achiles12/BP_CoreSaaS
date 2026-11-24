// Route guard, layer 1 (B08 D5, object 10). Next.js 16 calls this file
// "proxy" (formerly middleware.ts, D2). It runs on the server before a page
// renders.
//
// It only checks that the httpOnly access cookie EXISTS; it never decodes or
// trusts it. Layer 2 ((app)/layout.tsx) asks the backend via /me, and the
// backend enforces everything. A missing access cookie does not mean the
// session is over: the refresh cookie (Path=/api/auth) is invisible here, so
// /login tries one silent refresh first (D6).
import { NextResponse, type NextRequest } from "next/server";

/** Same name the backend sets: COOKIE_PREFIX + base name (B13 D6). Read per call, not at import. */
export function accessCookie(): string {
  return `${process.env.COOKIE_PREFIX ?? ""}access_token`;
}

/** Pages reachable without a session. B09 pages are listed already. */
export const PUBLIC_PATHS = [
  "/login",
  "/403",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/accept-invite",
];

export function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = request.cookies.has(accessCookie());

  // Signed in and on /login -> /post-login picks the landing page
  // (ui_screens.md §3). Other public pages (reset, verify, invite links)
  // stay reachable while signed in (B09 D11).
  if (pathname === "/login" && signedIn) {
    return NextResponse.redirect(new URL("/post-login", request.url));
  }
  // B08's single /home page became per-role pages: a real 307 to
  // /post-login, which picks the user's own landing page (B09 D4).
  if (signedIn && pathname === "/home") {
    return NextResponse.redirect(new URL("/post-login", request.url));
  }
  if (isPublic(pathname) || signedIn) return NextResponse.next();

  const login = new URL("/login", request.url);
  login.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except the API proxy, Next internals and files with an
  // extension (favicon.ico, images, ...).
  matcher: ["/((?!api/|_next/|.*\\.[\\w]+$).*)"],
};
