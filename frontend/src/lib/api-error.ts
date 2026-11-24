// Error thrown by the fetcher for every non-2xx response (B08 D7). Mirrors
// the backend envelope {"error": {code, message, request_id, fields?}}
// (backend core/errors.py).

export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: FieldError[];
  readonly requestId?: string;
  /** Seconds from Retry-After (429), when present. */
  readonly retryAfter?: number;

  constructor(opts: {
    status: number;
    code: string;
    message: string;
    fields?: FieldError[];
    requestId?: string;
    retryAfter?: number;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.fields = opts.fields;
    this.requestId = opts.requestId;
    this.retryAfter = opts.retryAfter;
  }
}

/** status 0 = the request never got an HTTP answer (offline, DNS, CORS...). */
export const NETWORK_ERROR = 0;

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/**
 * Text for a toast or inline error (B10 D16): the API's own message when
 * there is one (it is written for users, e.g. "You cannot manage a member
 * with a more senior role"), otherwise `fallback`.
 */
export function errorMessage(
  e: unknown,
  fallback = "Something went wrong. Please try again.",
): string {
  if (isApiError(e)) {
    if (e.status === NETWORK_ERROR) return "Cannot reach the server. Check your connection.";
    if (e.code === "email_not_verified") return "Verify your email first.";
    if (e.message) return e.message;
  }
  return fallback;
}
