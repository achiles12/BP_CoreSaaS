"use client";
// Notifications bell (ui_screens S14, B10 D12). Polls the unread count every
// 30 s (and on window focus); the list loads only while the menu is open.
// Clicking an unread entry marks it read; an export.done entry also starts
// the download with a fresh link.
import { useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { getExport } from "@/api/generated/endpoints/exports/exports";
import {
  getListNotificationsQueryKey,
  markAllNotificationsRead,
  markNotificationRead,
  useListNotifications,
} from "@/api/generated/endpoints/notifications/notifications";
import type { MeOut, NotificationOut } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { errorMessage } from "@/lib/api-error";
import { openDownload } from "@/lib/files";
import { formatDateTime } from "@/lib/format";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";
import { cn } from "@/lib/utils";

export const COUNT_POLL_MS = 30_000;
export const LIST_SIZE = 10;

export function NotificationsBell({ me }: { me: MeOut }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const allowed = !!me.org && can(me, "notifications:read");
  const req = tenantRequest(me);
  // Hooks run unconditionally; `enabled` keeps them quiet when not allowed.
  const count = useListNotifications(
    { unread: true, page_size: 1 },
    {
      request: req,
      query: allowed
        ? { refetchInterval: COUNT_POLL_MS, refetchOnWindowFocus: true }
        : { enabled: false },
    },
  );
  const list = useListNotifications(
    { page: 1, page_size: LIST_SIZE },
    { request: req, query: { enabled: allowed && open } },
  );
  if (!allowed) return null;

  const unread = count.data?.total ?? 0;
  const refresh = () =>
    qc.invalidateQueries({ queryKey: getListNotificationsQueryKey().slice(0, 1) });

  async function select(n: NotificationOut) {
    try {
      if (!n.read_at) await markNotificationRead(n.id, req);
      if (n.type === "export.done" && typeof n.data.export_id === "string") {
        const job = await getExport(n.data.export_id, req);
        if (job.download_url) openDownload(job.download_url);
        else toast.info("This export is no longer available. Run it again from the list.");
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      void refresh();
    }
  }

  async function markAll() {
    try {
      await markAllNotificationsRead(req);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      void refresh();
    }
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={unread > 0 ? `Notifications (${unread} unread)` : "Notifications"}
          data-testid="bell"
        >
          <Bell className="size-5" />
          {unread > 0 && (
            <span className="bg-destructive absolute -top-0.5 -right-0.5 min-w-4 rounded-full px-1 text-[10px] leading-4 font-semibold text-white">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {!list.data ? (
          <p className="text-muted-foreground px-2 py-3 text-sm">Loading…</p>
        ) : list.data.items.length === 0 ? (
          <p className="text-muted-foreground px-2 py-3 text-sm">Nothing yet.</p>
        ) : (
          list.data.items.map((n) => (
            <DropdownMenuItem
              key={n.id}
              onSelect={() => void select(n)}
              className="flex flex-col items-start gap-0.5"
            >
              <span className={cn("text-sm", !n.read_at && "font-semibold")}>
                {!n.read_at && <span className="sr-only">Unread: </span>}
                {n.title}
              </span>
              {n.body && (
                <span className="text-muted-foreground line-clamp-2 text-xs">{n.body}</span>
              )}
              <span className="text-muted-foreground text-[11px]">
                {formatDateTime(n.created_at)}
              </span>
            </DropdownMenuItem>
          ))
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => void markAll()}
          disabled={unread === 0 && !list.data?.items.some((n) => !n.read_at)}
        >
          <CheckCheck className="size-4" aria-hidden /> Mark all read
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
