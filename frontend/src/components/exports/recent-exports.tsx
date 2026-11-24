"use client";
// The user's last exports (S13 "Recent exports list").
import { useListExports } from "@/api/generated/endpoints/exports/exports";
import type { MeOut } from "@/api/generated/model";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import { tenantRequest } from "@/lib/tenant";

export const RECENT_COUNT = 5;

export function RecentExports({
  me,
  enabled,
  onDownload,
}: {
  me: MeOut;
  enabled: boolean;
  onDownload: (id: string) => void;
}) {
  const q = useListExports(
    { page: 1, page_size: RECENT_COUNT },
    { request: tenantRequest(me), query: { enabled } },
  );
  if (!q.data || q.data.items.length === 0) return null;
  return (
    <section aria-label="Recent exports" className="border-t pt-3">
      <h3 className="text-muted-foreground mb-2 text-xs font-semibold uppercase">Recent exports</h3>
      <ul className="space-y-1 text-sm">
        {q.data.items.map((e) => (
          <li key={e.id} className="flex items-center justify-between gap-2">
            <span className="truncate">
              {e.resource} · {e.format.toUpperCase()} · {formatDateTime(e.created_at)}
            </span>
            {e.status === "done" ? (
              <Button size="sm" variant="ghost" onClick={() => onDownload(e.id)}>
                Download
              </Button>
            ) : (
              <Badge variant="outline">{e.status}</Badge>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
