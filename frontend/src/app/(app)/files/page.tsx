"use client";
// Files (ui_screens S08, B10 D4–D6): filters in the URL, upload dialog,
// download through a 60 s link, soft delete with confirmation, export.
import { useQueryClient } from "@tanstack/react-query";
import { Download, Trash2, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import {
  deleteFile,
  getListFilesQueryKey,
  useListFiles,
} from "@/api/generated/endpoints/files/files";
import type { FileOut, ListFilesParams, MeOut } from "@/api/generated/model";
import { ConfirmDialog } from "@/components/data/confirm";
import { DataTable, type Column } from "@/components/data/data-table";
import { Pager } from "@/components/data/pager";
import { RowMenu } from "@/components/data/row-menu";
import { SearchInput } from "@/components/data/search-input";
import { ExportButton } from "@/components/exports/export-dialog";
import { UploadDialog } from "@/components/files/upload-dialog";
import { GatedPage, PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox, NativeSelect } from "@/components/ui/native";
import { errorMessage } from "@/lib/api-error";
import { downloadFile } from "@/lib/files";
import { formatBytes, formatDate, mimeLabel } from "@/lib/format";
import { useListParams } from "@/lib/list-params";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";
import { MIME_GROUPS } from "@/lib/upload";

const PAGE_SIZE = 25;
// URL keys (D3). `type` is a MIME group key, `mine` is "1" when on.
const DEFAULTS = { q: "", type: "", mine: "", from: "", to: "" };
type Url = typeof DEFAULTS & { page: number };

/** URL state -> GET /files params (the export uses the same, as strings). */
export function filesApiParams(p: Url): ListFilesParams {
  const out: ListFilesParams = {};
  if (p.q) out.q = p.q;
  const group = MIME_GROUPS.find((g) => g.key === p.type);
  if (group) out["filter[mime_type]"] = group.types.join(",");
  if (p.mine === "1") out.mine = true;
  if (p.from) out["filter[created_at][gte]"] = p.from;
  if (p.to) out["filter[created_at][lte]"] = p.to; // a date-only upper bound covers the day (B06)
  return out;
}

function asStrings(p: ListFilesParams): Record<string, string> {
  return Object.fromEntries(Object.entries(p).map(([k, v]) => [k, String(v)]));
}

function FilesBody({ me }: { me: MeOut }) {
  const qc = useQueryClient();
  const { params, set } = useListParams(DEFAULTS);
  const [uploading, setUploading] = useState(false);
  const [toDelete, setToDelete] = useState<FileOut | null>(null);
  const filters = useMemo(() => filesApiParams(params), [params]);
  const hasFilters = Object.keys(filters).length > 0;
  const canWrite = can(me, "files:write");
  const canDelete = can(me, "files:delete");

  const q = useListFiles(
    { ...filters, page: params.page, page_size: PAGE_SIZE },
    { request: tenantRequest(me) },
  );

  async function confirmDelete() {
    if (!toDelete) return;
    try {
      await deleteFile(toDelete.id, tenantRequest(me));
      toast.success(`Deleted “${toDelete.name}”`);
      await qc.invalidateQueries({ queryKey: getListFilesQueryKey().slice(0, 1) });
    } catch (err) {
      toast.error(errorMessage(err, "Could not delete the file."));
    }
  }

  const columns: Column<FileOut>[] = [
    { key: "name", header: "Name", className: "font-medium" },
    { key: "size", header: "Size", cell: (f) => formatBytes(f.size_bytes) },
    { key: "type", header: "Type", cell: (f) => mimeLabel(f.mime_type) },
    { key: "uploader", header: "Uploaded by", cell: (f) => f.uploader_name ?? "—" },
    { key: "date", header: "Date", cell: (f) => formatDate(f.created_at) },
  ];

  const uploadButton = canWrite && (
    <Button onClick={() => setUploading(true)}>
      <Upload className="size-4" aria-hidden /> Upload
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Files"
        actions={
          <>
            <ExportButton
              resource="files"
              filters={asStrings(filters)}
              readPermission="files:read"
            />
            {uploadButton}
          </>
        }
      />
      <div className="flex flex-wrap items-end gap-2">
        <SearchInput value={params.q} onChange={(v) => set({ q: v })} placeholder="Search files…" />
        <label className="text-sm">
          <span className="sr-only">Type</span>
          <NativeSelect
            aria-label="Type"
            value={params.type}
            onChange={(e) => set({ type: e.target.value })}
            className="w-36"
          >
            <option value="">All types</option>
            {MIME_GROUPS.map((g) => (
              <option key={g.key} value={g.key}>
                {g.label}
              </option>
            ))}
          </NativeSelect>
        </label>
        <label className="flex h-9 items-center gap-2 text-sm">
          <Checkbox
            checked={params.mine === "1"}
            onChange={(e) => set({ mine: e.target.checked ? "1" : "" })}
          />
          Mine only
        </label>
        <label className="text-muted-foreground flex items-center gap-1 text-sm">
          From
          <Input
            type="date"
            value={params.from}
            onChange={(e) => set({ from: e.target.value })}
            className="w-40"
            aria-label="From date"
          />
        </label>
        <label className="text-muted-foreground flex items-center gap-1 text-sm">
          To
          <Input
            type="date"
            value={params.to}
            onChange={(e) => set({ to: e.target.value })}
            className="w-40"
            aria-label="To date"
          />
        </label>
      </div>

      <DataTable
        testId="files-table"
        columns={columns}
        rows={q.data?.items}
        isLoading={q.isPending}
        error={q.isError ? q.error : undefined}
        rowKey={(f) => f.id}
        empty={
          hasFilters ? (
            "No files match these filters."
          ) : (
            <div className="space-y-3">
              <p className="text-foreground text-base font-medium">No files yet</p>
              <p>Upload your first file to share it with your organization.</p>
              {uploadButton}
            </div>
          )
        }
        rowActions={(f) => (
          <RowMenu
            label={f.name}
            items={[
              {
                label: "Download",
                icon: <Download className="size-4" />,
                onSelect: () => void downloadFile(me, f.id),
              },
              ...(canDelete
                ? [
                    {
                      label: "Delete",
                      icon: <Trash2 className="size-4" />,
                      destructive: true,
                      onSelect: () => setToDelete(f),
                    },
                  ]
                : []),
            ]}
          />
        )}
      />
      {q.data && q.data.total > 0 && (
        <Pager
          page={params.page}
          pageSize={PAGE_SIZE}
          total={q.data.total}
          onPage={(page) => set({ page })}
        />
      )}

      {canWrite && <UploadDialog me={me} open={uploading} onOpenChange={setUploading} />}
      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={`Delete “${toDelete?.name ?? ""}”?`}
        body="It disappears from the list now; storage is cleaned up later."
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
      />
    </>
  );
}

export default function FilesPage() {
  return (
    <GatedPage perm="files:read" wide>
      {(me) => <FilesBody me={me} />}
    </GatedPage>
  );
}
