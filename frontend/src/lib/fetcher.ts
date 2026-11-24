// Fetch mutator used by every orval-generated hook (B08 D7, object 4).
//
//  - prefixes "/api" (Next.js rewrites it to FastAPI, B08 D17)
//  - credentials: "include" so the httpOnly auth cookies travel
//  - X-Tenant from the session org (lib/org.ts)
//  - non-2xx -> ApiError built from the backend error envelope
//  - 401 -> ONE shared /auth/refresh, then retry the request once.
//
// Why single-flight: the backend treats a second use of the same refresh
// token as theft and revokes the whole token family (B03 D10, no grace
// window). If three queries 401 at once and each refreshed on its own, two of
// them would present an already-rotated token and log the user out. So every
// caller awaits the same promise.
import { ApiError, NETWORK_ERROR, type FieldError } from "./api-error";
import { log } from "./log";
import { getOrg } from "./org";

export const API_PREFIX = "/api";
export const TENANT_HEADER = "X-Tenant";

/** Paths (without /api) that must never trigger a refresh: they ARE the auth flow. */
export const NO_REFRESH_PATHS = ["/auth/login", "/auth/refresh", "/auth/logout"];

// ----------------------------------------------------------------- events --
type Listener = () => void;
const expiredListeners = new Set<Listener>();

/** Subscribe to "the session is gone" (refresh failed). Returns unsubscribe. */
export function onSessionExpired(cb: Listener): () => void {
  expiredListeners.add(cb);
  return () => expiredListeners.delete(cb);
}

function emitSessionExpired(): void {
  log.warn("auth.session_expired");
  expiredListeners.forEach((cb) => {
    try {
      cb();
    } catch (err) {
      log.error("auth.session_expired_listener_failed", { err: String(err) });
    }
  });
}

// --------------------------------------------------------------- refresh --
let inflight: Promise<boolean> | null = null;

/**
 * Rotate the auth cookies. Concurrent callers share one request; the promise
 * is dropped once it settles so a later 401 can refresh again.
 * Resolves true on 2xx, false otherwise (never rejects).
 */
export function refreshOnce(): Promise<boolean> {
  if (inflight) {
    log.debug("auth.refresh_joined");
    return inflight;
  }
  log.debug("auth.refresh_start");
  inflight = fetch(`${API_PREFIX}/auth/refresh`, { method: "POST", credentials: "include" })
    .then((res) => {
      log.debug("auth.refresh_done", { status: res.status });
      return res.ok;
    })
    .catch((err: unknown) => {
      log.warn("auth.refresh_network_error", { err: String(err) });
      return false;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

// ---------------------------------------------------------------- helpers --
function pathOf(url: string): string {
  // Generated URLs are relative ("/me?x=1"); strip the query for matching.
  return url.split("?")[0] ?? url;
}

function buildHeaders(init: RequestInit): Headers {
  const headers = new Headers(init.headers);
  // A caller passing X-Tenant: "" opts out of the header (used by /me, D8).
  if (headers.has(TENANT_HEADER)) {
    if (!headers.get(TENANT_HEADER)) headers.delete(TENANT_HEADER);
  } else {
    const org = getOrg();
    if (org) headers.set(TENANT_HEADER, org);
  }
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

async function parseBody(res: Response): Promise<unknown> {
  if (res.status === 204 || res.status === 205) return undefined;
  const text = await res.text();
  if (!text) return undefined;
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

async function toApiError(res: Response): Promise<ApiError> {
  const body = (await parseBody(res).catch(() => undefined)) as
    | { error?: { code?: string; message?: string; request_id?: string; fields?: FieldError[] } }
    | undefined;
  const err = typeof body === "object" && body ? body.error : undefined;
  const retry = Number(res.headers.get("retry-after"));
  return new ApiError({
    status: res.status,
    code: err?.code ?? `http_${res.status}`,
    message: err?.message ?? (res.statusText || `Request failed (${res.status})`),
    fields: err?.fields,
    requestId: err?.request_id ?? res.headers.get("x-request-id") ?? undefined,
    retryAfter: Number.isFinite(retry) && retry > 0 ? retry : undefined,
  });
}

// ---------------------------------------------------------------- mutator --
/** orval picks these up from the mutator file: hook errors are typed ApiError. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export type ErrorType<_E> = ApiError;
export type BodyType<B> = B;

/**
 * orval mutator. `url` is the backend path ("/me"); returns the parsed JSON
 * body typed as T, or throws ApiError.
 */
export async function customFetch<T>(url: string, init: RequestInit = {}): Promise<T> {
  const path = pathOf(url);
  const send = () =>
    fetch(`${API_PREFIX}${url}`, { ...init, headers: buildHeaders(init), credentials: "include" });

  let res: Response;
  try {
    res = await send();
    if (res.status === 401 && !NO_REFRESH_PATHS.includes(path)) {
      log.debug("auth.401", { path });
      if (await refreshOnce()) {
        res = await send(); // retry exactly once
        if (res.status === 401) emitSessionExpired();
      } else {
        emitSessionExpired();
      }
    }
  } catch (err) {
    // AbortError is a normal cancellation (React Query unmount): rethrow as is.
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    log.warn("api.network_error", { path, err: String(err) });
    throw new ApiError({
      status: NETWORK_ERROR,
      code: "network_error",
      message: "Cannot reach the server",
    });
  }

  if (!res.ok) {
    const apiErr = await toApiError(res);
    log.debug("api.error", {
      path,
      status: apiErr.status,
      code: apiErr.code,
      id: apiErr.requestId,
    });
    throw apiErr;
  }
  return (await parseBody(res)) as T;
}

/** Test hook: drop a stuck in-flight refresh between tests. */
export function _resetFetcherForTests(): void {
  inflight = null;
  expiredListeners.clear();
}
