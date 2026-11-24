// Browser upload (B10 D5, backend_processes §6):
//   1. POST /files/presign-upload   -> file_id, upload_url, signed headers
//   2. PUT the bytes straight to RustFS with XMLHttpRequest
//   3. POST /files/{id}/confirm     -> the file becomes active
// XHR, not fetch: fetch cannot report upload progress. The PUT must carry the
// signed Content-Type exactly (B05 D6) and no credentials (RustFS is another
// origin and the URL itself is the authorisation).
import { confirmUpload, presignUpload } from "@/api/generated/endpoints/files/files";
import type { FileOut, MeOut } from "@/api/generated/model";
import { MAX_UPLOAD_MB, UPLOAD_MIME_TYPES } from "@/config/site";

import { log } from "./log";
import { tenantRequest } from "./tenant";

/** Type filter groups on /files (D4): label -> MIME types for filter[mime_type]. */
export const MIME_GROUPS: { key: string; label: string; types: string[] }[] = [
  { key: "pdf", label: "PDF", types: ["application/pdf"] },
  { key: "image", label: "Images", types: ["image/png", "image/jpeg", "image/gif", "image/webp"] },
  {
    key: "word",
    label: "Word",
    types: [
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "application/msword",
    ],
  },
  {
    key: "excel",
    label: "Excel / CSV",
    types: [
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "application/vnd.ms-excel",
      "text/csv",
    ],
  },
  { key: "text", label: "Text", types: ["text/plain"] },
  { key: "zip", label: "Zip", types: ["application/zip"] },
];

/** Why `file` cannot be uploaded, or null when it can. */
export function validateFile(
  file: File,
  maxMb: number = MAX_UPLOAD_MB,
  allowed: string[] = UPLOAD_MIME_TYPES,
): string | null {
  if (file.size === 0) return `“${file.name}” is empty.`;
  if (file.size > maxMb * 1024 * 1024) return `“${file.name}” is larger than ${maxMb} MB.`;
  // Browsers report "" for unknown extensions (.md, .log): the API needs a type.
  if (!file.type || !allowed.includes(file.type.toLowerCase())) {
    return `“${file.name}”: this file type is not allowed.`;
  }
  return null;
}

/** PUT to the presigned URL; resolves on 2xx, rejects with a readable error. */
function putToStorage(
  url: string,
  headers: Record<string, string>,
  file: File,
  onProgress: (pct: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`File storage refused the upload (HTTP ${xhr.status}).`));
    };
    xhr.onerror = () => reject(new Error("Could not reach file storage. Check your connection."));
    xhr.onabort = () => reject(new Error("Upload cancelled."));
    if (signal) {
      if (signal.aborted) {
        xhr.abort();
        return;
      }
      signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    xhr.send(file);
  });
}

export async function uploadFile(
  file: File,
  opts: { me: MeOut; onProgress: (pct: number) => void; signal?: AbortSignal },
): Promise<FileOut> {
  const req = tenantRequest(opts.me);
  const presigned = await presignUpload(
    { name: file.name, mime_type: file.type, size_bytes: file.size },
    req,
  );
  log.info("files.upload_start", { fileId: presigned.file_id, size: file.size });
  await putToStorage(
    presigned.upload_url,
    presigned.headers as Record<string, string>,
    file,
    opts.onProgress,
    opts.signal,
  );
  opts.onProgress(100);
  const out = await confirmUpload(presigned.file_id, req);
  log.info("files.upload_done", { fileId: presigned.file_id });
  return out;
}
