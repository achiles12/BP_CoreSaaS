// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { config, isPublic, proxy } from "./proxy";

function req(path: string, cookie?: string) {
  return new NextRequest(`http://localhost:3200${path}`, {
    headers: cookie ? { cookie } : {},
  });
}

describe("proxy.ts guard (D5)", () => {
  it("redirects a signed-out page request to /login?next=", () => {
    const res = proxy(req("/home?tab=2"));
    expect(res.status).toBe(307);
    const loc = new URL(res.headers.get("location")!);
    expect(loc.pathname).toBe("/login");
    expect(loc.searchParams.get("next")).toBe("/home?tab=2");
  });

  it("lets a request with an access cookie through", () => {
    const res = proxy(req("/home/owner", "access_token=abc"));
    expect(res.headers.get("x-middleware-next")).toBe("1");
  });

  it("sends a signed-in user from /login to /post-login", () => {
    const res = proxy(req("/login", "access_token=abc"));
    expect(new URL(res.headers.get("location")!).pathname).toBe("/post-login");
  });

  it("signed-in /home -> /post-login (B09)", () => {
    const res = proxy(req("/home", "access_token=abc"));
    expect(new URL(res.headers.get("location")!).pathname).toBe("/post-login");
  });

  it("email-link pages stay open while signed in (B09 D11)", () => {
    const res = proxy(req("/reset-password?token=x", "access_token=abc"));
    expect(res.headers.get("x-middleware-next")).toBe("1");
  });

  it("public pages need no cookie", () => {
    for (const p of ["/login", "/403", "/reset-password", "/accept-invite"]) {
      expect(proxy(req(p)).headers.get("x-middleware-next")).toBe("1");
    }
    expect(isPublic("/loginx")).toBe(false);
  });

  it("matcher skips /api, /_next and files", () => {
    const re = new RegExp(`^${config.matcher[0]}$`);
    expect(re.test("/home")).toBe(true);
    expect(re.test("/api/me")).toBe(false);
    expect(re.test("/_next/static/x.js")).toBe(false);
    expect(re.test("/favicon.ico")).toBe(false);
  });
});

describe("cookie prefix (B13 D6)", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("accepts only the prefixed cookie", () => {
    vi.stubEnv("COOKIE_PREFIX", "acme_");
    const ok = proxy(req("/home/owner", "acme_access_token=abc"));
    expect(ok.headers.get("x-middleware-next")).toBe("1");
    const other = proxy(req("/home/owner", "access_token=abc"));
    expect(new URL(other.headers.get("location")!).pathname).toBe("/login");
  });

  it("uses the plain name when the prefix is empty", () => {
    vi.stubEnv("COOKIE_PREFIX", "");
    const res = proxy(req("/home/owner", "access_token=abc"));
    expect(res.headers.get("x-middleware-next")).toBe("1");
  });
});
