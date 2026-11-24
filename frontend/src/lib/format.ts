// Display helpers for table cells (B10 §3.1).

const UNITS = ["B", "KB", "MB", "GB", "TB"];

/** 1536 -> "1.5 KB"; one decimal below 10 units, none above. */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 1024) return `${Math.max(0, Math.round(n || 0))} B`;
  let v = n;
  let i = 0;
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024;
    i++;
  }
  const s = v < 10 ? v.toFixed(1).replace(/\.0$/, "") : String(Math.round(v));
  return `${s} ${UNITS[i]}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** ISO -> "2026-11-20" in the viewer's time zone; null -> "—". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** ISO -> "2026-11-20 16:30". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${formatDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Short type label for a MIME type (Files "Type" column). */
export function mimeLabel(mime: string): string {
  const m = mime.toLowerCase();
  if (m === "application/pdf") return "PDF";
  if (m.startsWith("image/")) return "Image";
  if (m.includes("wordprocessingml") || m === "application/msword") return "Word";
  if (m.includes("spreadsheetml") || m === "application/vnd.ms-excel") return "Excel";
  if (m.includes("presentationml") || m === "application/vnd.ms-powerpoint") return "PowerPoint";
  if (m === "text/csv") return "CSV";
  if (m.startsWith("text/")) return "Text";
  if (m === "application/zip" || m === "application/x-zip-compressed") return "Zip";
  return "File";
}
