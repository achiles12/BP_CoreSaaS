// File download (B10 D6): ask the API for a 60 s presigned URL, then let the
// browser fetch it. RustFS answers with Content-Disposition: attachment and
// the original name (B05), so the page stays where it is.
import { toast } from "sonner";

import { downloadUrl } from "@/api/generated/endpoints/files/files";
import type { MeOut } from "@/api/generated/model";

import { errorMessage } from "./api-error";
import { log } from "./log";
import { tenantRequest } from "./tenant";

/** Open a URL as a download without leaving the page. */
export function openDownload(url: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export async function downloadFile(me: MeOut, fileId: string): Promise<void> {
  try {
    const out = await downloadUrl(fileId, tenantRequest(me));
    openDownload(out.url);
    log.info("files.download", { fileId });
  } catch (err) {
    log.warn("files.download_failed", { fileId, err: String(err) });
    toast.error(errorMessage(err, "Could not download the file."));
  }
}
