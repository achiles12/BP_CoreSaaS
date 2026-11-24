"use client";
// Export dialog (ui_screens S13, app_flows F9, B10 D11):
//   choose format -> POST /exports with the list's filters -> poll every 2 s
//   -> "Download" (a fresh 60 s link is fetched on click, so it never expires
//   on the user). Polling stops when the job ends or the dialog closes.
import { useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  createExport,
  getExport,
  getListExportsQueryKey,
} from "@/api/generated/endpoints/exports/exports";
import type { ExportOut, MeOut } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errorMessage } from "@/lib/api-error";
import { useSession } from "@/lib/auth";
import { openDownload } from "@/lib/files";
import { log } from "@/lib/log";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";

import { RecentExports } from "./recent-exports";

export const POLL_MS = 2000; // app_flows F9
type Format = "csv" | "xlsx";
type State =
  | { step: "choose" }
  | { step: "running"; job?: ExportOut }
  | { step: "done"; job: ExportOut }
  | { step: "failed"; message: string };

/** Fetch a fresh link for a finished export and start the download. */
export async function downloadExport(me: MeOut, id: string): Promise<string | null> {
  const job = await getExport(id, tenantRequest(me));
  if (job.download_url) {
    openDownload(job.download_url);
    return null;
  }
  return job.status === "expired"
    ? "This export has expired. Run it again."
    : "The file is not available any more. Run the export again.";
}

function ExportDialog({
  me,
  resource,
  filters,
  open,
  onOpenChange,
}: {
  me: MeOut;
  resource: string;
  filters: Record<string, string>;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const qc = useQueryClient();
  const [format, setFormat] = useState<Format>("csv");
  const [state, setState] = useState<State>({ step: "choose" });
  const alive = useRef(false); // false once the dialog closes: stops polling

  useEffect(() => {
    alive.current = open;
    return () => {
      alive.current = false;
    };
  }, [open]);

  // Closing resets the dialog (and the effect above stops any polling).
  function change(o: boolean) {
    if (!o) setState({ step: "choose" });
    onOpenChange(o);
  }

  async function start() {
    setState({ step: "running" });
    try {
      let job = await createExport({ resource, format, filters }, tenantRequest(me));
      log.info("exports.started", { id: job.id, resource, format });
      while (alive.current && (job.status === "queued" || job.status === "running")) {
        setState({ step: "running", job });
        await new Promise((r) => setTimeout(r, POLL_MS));
        if (!alive.current) return;
        job = await getExport(job.id, tenantRequest(me));
      }
      if (!alive.current) return;
      void qc.invalidateQueries({ queryKey: getListExportsQueryKey().slice(0, 1) });
      if (job.status === "done") setState({ step: "done", job });
      else setState({ step: "failed", message: job.error || `Export ${job.status}.` });
    } catch (err) {
      if (alive.current) setState({ step: "failed", message: errorMessage(err) });
    }
  }

  async function download(id: string) {
    try {
      const problem = await downloadExport(me, id);
      if (problem) setState({ step: "failed", message: problem });
    } catch (err) {
      setState({ step: "failed", message: errorMessage(err) });
    }
  }

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export {resource}</DialogTitle>
          <DialogDescription>
            Exports the rows that match your current search and filters (all pages).
          </DialogDescription>
        </DialogHeader>

        {state.step === "choose" && (
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Format</legend>
            {(["csv", "xlsx"] as const).map((f) => (
              <label key={f} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="export-format"
                  value={f}
                  checked={format === f}
                  onChange={() => setFormat(f)}
                />
                {f === "csv" ? "CSV (opens in Excel)" : "Excel (XLSX)"}
              </label>
            ))}
          </fieldset>
        )}
        {state.step === "running" && (
          <p className="text-sm" role="status" aria-live="polite">
            Preparing your file… {state.job ? `(${state.job.status})` : ""}
          </p>
        )}
        {state.step === "done" && (
          <div className="space-y-2" role="status">
            <p className="text-sm">
              Ready: {state.job.row_count} rows, {state.job.format.toUpperCase()}.
            </p>
            <Button onClick={() => download(state.job.id)}>
              <Download className="size-4" aria-hidden /> Download
            </Button>
          </div>
        )}
        {state.step === "failed" && (
          <p className="text-destructive text-sm" role="alert">
            {state.message}
          </p>
        )}

        <RecentExports me={me} enabled={open} onDownload={download} />

        <DialogFooter>
          <Button variant="outline" onClick={() => change(false)}>
            Close
          </Button>
          {(state.step === "choose" || state.step === "failed") && (
            <Button onClick={start}>Export</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The "Export" button of a list (D11). Hidden unless the user may run
 * exports AND read the list (the API checks both, B07 D3).
 */
export function ExportButton({
  resource,
  filters,
  readPermission,
}: {
  resource: "files" | "items" | "users" | string;
  filters: Record<string, string>;
  readPermission: string;
}) {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  if (!me || !can(me, "export:run") || !can(me, readPermission)) return null;
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Download className="size-4" aria-hidden /> Export
      </Button>
      <ExportDialog
        me={me}
        resource={resource}
        filters={filters}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}
