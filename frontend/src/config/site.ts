// Product-wide constants.
export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Core SaaS";
export const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV ?? "dev";
/** Mailpit web UI port on the dev host (dev banner, ui_screens.md §5). */
export const MAILPIT_PORT = process.env.NEXT_PUBLIC_MAILPIT_PORT ?? "8025";

// Upload checks before anything is sent (B10 D5). Compose passes the
// backend's MAX_UPLOAD_MB / ALLOWED_MIME_TYPES; the backend stays the
// authority (413/415 are still shown if the two ever disagree).
export const DEFAULT_ALLOWED_MIME_TYPES = [
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "text/plain",
  "text/csv",
  "application/zip",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/msword",
  "application/vnd.ms-excel",
  "application/vnd.ms-powerpoint",
];
export const MAX_UPLOAD_MB = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB) || 50;
export const ALLOWED_MIME_TYPES = (process.env.NEXT_PUBLIC_ALLOWED_MIME_TYPES ?? "")
  .split(",")
  .map((m) => m.trim().toLowerCase())
  .filter(Boolean);
/** The effective list: env when set, else the backend default. */
export const UPLOAD_MIME_TYPES =
  ALLOWED_MIME_TYPES.length > 0 ? ALLOWED_MIME_TYPES : DEFAULT_ALLOWED_MIME_TYPES;
