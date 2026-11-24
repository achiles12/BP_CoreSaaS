import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse } from "@/test/fixtures";

import { ApiError } from "./api-error";
import { _resetFetcherForTests, customFetch, onSessionExpired, refreshOnce } from "./fetcher";
import { _resetOrgForTests, setOrg } from "./org";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  _resetFetcherForTests();
  _resetOrgForTests();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const calls = () => fetchMock.mock.calls.map(([u]) => String(u));
const headersOf = (i: number) => new Headers(fetchMock.mock.calls[i]![1]!.headers);

describe("customFetch", () => {
  it("prefixes /api, sends credentials and parses JSON", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: 1 }));
    await expect(customFetch("/me", { method: "GET" })).resolves.toEqual({ ok: 1 });
    expect(calls()).toEqual(["/api/me"]);
    expect(fetchMock.mock.calls[0]![1]!.credentials).toBe("include");
  });

  it("adds X-Tenant from the org state, and JSON content type for string bodies", async () => {
    setOrg("acme");
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    await customFetch("/users", { method: "POST", body: "{}" });
    expect(headersOf(0).get("X-Tenant")).toBe("acme");
    expect(headersOf(0).get("Content-Type")).toBe("application/json");
  });

  it("omits X-Tenant when the caller passes an empty one (/me, D8)", async () => {
    setOrg("acme");
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    await customFetch("/me", { headers: { "X-Tenant": "" } });
    expect(headersOf(0).has("X-Tenant")).toBe(false);
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(customFetch("/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("maps the error envelope to ApiError", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        429,
        { error: { code: "rate_limited", message: "Too many requests", request_id: "r1" } },
        { "retry-after": "42" },
      ),
    );
    const err = await customFetch("/auth/login", { method: "POST" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 429,
      code: "rate_limited",
      message: "Too many requests",
      requestId: "r1",
      retryAfter: 42,
    });
  });

  it("turns a network failure into ApiError status 0", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(customFetch("/me")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("on 401 refreshes once and retries the request", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: "unauthenticated" } }))
      .mockResolvedValueOnce(jsonResponse(200, { user: {} })) // refresh
      .mockResolvedValueOnce(jsonResponse(200, { me: true })); // retry
    await expect(customFetch("/me")).resolves.toEqual({ me: true });
    expect(calls()).toEqual(["/api/me", "/api/auth/refresh", "/api/me"]);
  });

  it("three concurrent 401s share exactly ONE refresh (B03 D10)", async () => {
    let releaseRefresh!: (r: Response) => void;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/auth/refresh") {
        return new Promise<Response>((res) => (releaseRefresh = res));
      }
      const n = fetchMock.mock.calls.filter(([u]) => String(u) === url).length;
      return Promise.resolve(n === 1 ? jsonResponse(401, {}) : jsonResponse(200, { url }));
    });
    const all = Promise.all([customFetch("/a"), customFetch("/b"), customFetch("/c")]);
    await vi.waitFor(() => expect(calls()).toContain("/api/auth/refresh"));
    // give the other two 401s time to arrive and join the in-flight refresh
    await new Promise((r) => setTimeout(r, 10));
    releaseRefresh(jsonResponse(200, {}));
    await expect(all).resolves.toEqual([{ url: "/api/a" }, { url: "/api/b" }, { url: "/api/c" }]);
    expect(calls().filter((u) => u === "/api/auth/refresh")).toHaveLength(1);
  });

  it("a failed refresh emits session-expired and throws 401", async () => {
    const expired = vi.fn();
    onSessionExpired(expired);
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(401, { error: { code: "unauthenticated", message: "x" } }),
      )
      .mockResolvedValueOnce(jsonResponse(401, {})); // refresh fails
    await expect(customFetch("/me")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it("never refreshes for the auth endpoints themselves", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { error: { code: "unauthenticated" } }));
    await expect(customFetch("/auth/login", { method: "POST" })).rejects.toMatchObject({
      status: 401,
    });
    expect(calls()).toEqual(["/api/auth/login"]);
  });

  it("refreshOnce resolves false on network error and can run again afterwards", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("down"));
    await expect(refreshOnce()).resolves.toBe(false);
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    await expect(refreshOnce()).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
