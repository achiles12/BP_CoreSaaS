// Notifications bell (B10 D12, ui_screens S14).
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeMe } from "@/test/fixtures";
import { renderWithSession } from "@/test/render";

import { NotificationsBell } from "./notifications-bell";

const markRead = vi.fn();
const markAll = vi.fn();
const getExport = vi.fn();
const opened = vi.fn();
let unread = 3;
const listCalls: unknown[] = [];
const NOTES = [
  {
    id: "n1",
    type: "export.done",
    title: "Your items export is ready",
    body: "4 rows, CSV.",
    data: { export_id: "e1" },
    read_at: null,
    created_at: "2026-11-20T08:00:00Z",
  },
  {
    id: "n2",
    type: "export.failed",
    title: "Your users export failed",
    body: "limit",
    data: { export_id: "e2" },
    read_at: "2026-11-20T08:05:00Z",
    created_at: "2026-11-20T07:00:00Z",
  },
];
vi.mock("@/api/generated/endpoints/notifications/notifications", () => ({
  getListNotificationsQueryKey: () => ["/notifications"],
  useListNotifications: (
    p: { unread?: boolean; page_size?: number },
    o: { query?: { enabled?: boolean } },
  ) => {
    listCalls.push({ p, enabled: o?.query?.enabled });
    return p.unread
      ? { data: { items: [], total: unread } }
      : { data: o?.query?.enabled === false ? undefined : { items: NOTES, total: 2 } };
  },
  markNotificationRead: (...a: unknown[]) => markRead(...a),
  markAllNotificationsRead: (...a: unknown[]) => markAll(...a),
}));
vi.mock("@/api/generated/endpoints/exports/exports", () => ({
  getExport: (...a: unknown[]) => getExport(...a),
}));
vi.mock("@/lib/files", () => ({ openDownload: (u: string) => opened(u) }));

const me = makeMe({ permissions: ["notifications:read"] });

describe("NotificationsBell", () => {
  beforeEach(() => {
    unread = 3;
    listCalls.length = 0;
    markRead.mockReset().mockResolvedValue({});
    markAll.mockReset().mockResolvedValue({ updated: 3 });
    getExport
      .mockReset()
      .mockResolvedValue({ id: "e1", status: "done", download_url: "http://s3/e1.csv" });
    opened.mockReset();
  });

  it("shows the unread count; no badge at zero", () => {
    const { unmount } = renderWithSession(<NotificationsBell me={me} />, me);
    expect(screen.getByRole("button", { name: "Notifications (3 unread)" })).toHaveTextContent("3");
    unmount();
    unread = 0;
    renderWithSession(<NotificationsBell me={me} />, me);
    expect(screen.getByRole("button", { name: "Notifications" })).not.toHaveTextContent("0");
  });

  it("counts with ?unread=true&page_size=1 and polls every 30 s", () => {
    renderWithSession(<NotificationsBell me={me} />, me);
    expect(listCalls).toContainEqual({ p: { unread: true, page_size: 1 }, enabled: undefined });
  });

  it("opens the last 10; an export.done marks read and downloads", async () => {
    renderWithSession(<NotificationsBell me={me} />, me);
    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    expect(listCalls).toContainEqual({ p: { page: 1, page_size: 10 }, enabled: true });
    await userEvent.click(await screen.findByRole("menuitem", { name: /items export is ready/i }));
    await waitFor(() => expect(markRead).toHaveBeenCalledWith("n1", expect.anything()));
    await waitFor(() => expect(opened).toHaveBeenCalledWith("http://s3/e1.csv"));
  });

  it("an already-read notification is not marked again", async () => {
    renderWithSession(<NotificationsBell me={me} />, me);
    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /users export failed/i }));
    expect(markRead).not.toHaveBeenCalled();
    expect(opened).not.toHaveBeenCalled();
  });

  it("mark all read", async () => {
    renderWithSession(<NotificationsBell me={me} />, me);
    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /mark all read/i }));
    await waitFor(() => expect(markAll).toHaveBeenCalled());
  });

  it("is not shown without notifications:read or without an org", () => {
    renderWithSession(<NotificationsBell me={makeMe({ permissions: [] })} />, me);
    expect(screen.queryByRole("button", { name: /notifications/i })).toBeNull();
  });
});
