"use client";
// Upload dialog (wireframe S08, B10 D5): drop or browse several files; each
// gets its own row with a progress bar or the reason it was refused.
// Files go one after another, so a slow link is not split six ways.
import { useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { getListFilesQueryKey } from "@/api/generated/endpoints/files/files";
import type { MeOut } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/native";
import { MAX_UPLOAD_MB } from "@/config/site";
import { errorMessage } from "@/lib/api-error";
import { formatBytes } from "@/lib/format";
import { uploadFile, validateFile } from "@/lib/upload";
import { cn } from "@/lib/utils";

type Status = "waiting" | "uploading" | "done" | "error";
interface Entry {
  id: number;
  file: File;
  status: Status;
  pct: number;
  error?: string;
}

let nextId = 1;

export function UploadDialog({
  me,
  open,
  onOpenChange,
}: {
  me: MeOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const busy = entries.some((e) => e.status === "uploading" || e.status === "waiting");

  function patch(id: number, p: Partial<Entry>) {
    setEntries((list) => list.map((e) => (e.id === id ? { ...e, ...p } : e)));
  }

  async function addFiles(files: FileList | File[]) {
    const fresh: Entry[] = Array.from(files).map((file) => {
      const error = validateFile(file);
      return {
        id: nextId++,
        file,
        status: error ? "error" : "waiting",
        pct: 0,
        error: error ?? undefined,
      };
    });
    setEntries((list) => [...list, ...fresh]);
    const ctl = new AbortController();
    abortRef.current = ctl;
    let uploaded = 0;
    for (const e of fresh.filter((x) => x.status === "waiting")) {
      if (ctl.signal.aborted) {
        patch(e.id, { status: "error", error: "Cancelled." });
        continue;
      }
      patch(e.id, { status: "uploading" });
      try {
        await uploadFile(e.file, {
          me,
          signal: ctl.signal,
          onProgress: (pct) => patch(e.id, { pct }),
        });
        patch(e.id, { status: "done", pct: 100 });
        uploaded++;
      } catch (err) {
        patch(e.id, { status: "error", error: errorMessage(err, (err as Error).message) });
      }
    }
    if (uploaded > 0) {
      await qc.invalidateQueries({ queryKey: getListFilesQueryKey().slice(0, 1) });
      toast.success(uploaded === 1 ? "File uploaded" : `${uploaded} files uploaded`);
    }
  }

  function close(o: boolean) {
    if (o) return onOpenChange(true);
    abortRef.current?.abort(); // a pending row is cleaned up by J04 later
    setEntries([]);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload files</DialogTitle>
          <DialogDescription>
            Up to {MAX_UPLOAD_MB} MB each. PDF, images, Office documents, text, CSV and zip.
          </DialogDescription>
        </DialogHeader>
        <div
          data-testid="dropzone"
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (e.dataTransfer.files.length) void addFiles(e.dataTransfer.files);
          }}
          className={cn(
            "text-muted-foreground rounded-lg border-2 border-dashed p-6 text-center text-sm",
            dragging && "border-primary bg-muted",
          )}
        >
          <Upload className="mx-auto mb-2 size-6" aria-hidden />
          Drag files here or{" "}
          <button
            type="button"
            className="text-primary underline"
            onClick={() => inputRef.current?.click()}
          >
            browse
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            aria-label="Choose files"
            onChange={(e) => {
              if (e.target.files?.length) void addFiles(e.target.files);
              e.target.value = ""; // same file again triggers change
            }}
          />
        </div>
        {entries.length > 0 && (
          <ul className="space-y-3" aria-label="Uploads">
            {entries.map((e) => (
              <li key={e.id} className="space-y-1 text-sm">
                <div className="flex justify-between gap-2">
                  <span className="truncate">
                    {e.file.name}{" "}
                    <span className="text-muted-foreground">· {formatBytes(e.file.size)}</span>
                  </span>
                  <span className={cn(e.status === "error" && "text-destructive")}>
                    {e.status === "done"
                      ? "Done"
                      : e.status === "waiting"
                        ? "Waiting"
                        : e.status === "uploading"
                          ? `${e.pct}%`
                          : ""}
                  </span>
                </div>
                {e.status === "error" ? (
                  <p className="text-destructive text-xs" role="alert">
                    {e.error}
                  </p>
                ) : (
                  <Progress value={e.pct} label={`Upload ${e.file.name}`} />
                )}
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant={busy ? "outline" : "default"} onClick={() => close(false)}>
            {busy ? "Cancel" : "Done"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
