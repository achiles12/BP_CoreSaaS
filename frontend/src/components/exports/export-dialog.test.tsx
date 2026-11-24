// Export dialog (B10 D11; review focus 2).
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeMe } from "@/test/fixtures";
import { renderWithSession } from "@/test/render";

import { ExportButton, POLL_MS } from "./export-dialog";

const create = vi.fn();
const get = vi.fn();
vi.mock("@/api/generated/endpoints/exports/exports", () => ({
  createExport: (...a: unknown[]) => create(...a),
  getExport: (...a: unknown[]) => get(...a),
  getListExportsQueryKey: () => ["/exports"],
  useListExports: () => ({
    data: {
      items: [
        {
          id: "old1",
          resource: "items",
          format: "csv",
          status: "done",
          created_at: "2026-11-19T10:00:00Z",
        },
        {
          id: "old2",
          resource: "files",
          format: "xlsx",
          status: "failed",
          created_at: "2026-11-19T09:00:00Z",
        },
      ],
      total: 2,
    },
  }),
}));
const opened = vi.fn();
vi.mock("@/lib/files", () => ({ openDownload: (u: string) => opened(u) }));

const ME = makeMe({ permissions: ["export:run", "items:read"] });
const job = (status: string, extra: object = {}) => ({
  id: "e1",
  resource: "items",
  format: "csv",
  status,
  row_count: status === "done" ? 4 : null,
  error: null,
  download_url: null,
  ...extra,
});

function renderButton(me = ME) {
  return renderWithSession(
    <ExportButton
      resource="items"
      filters={{ q: "plan", "filter[status]": "open" }}
      readPermission="items:read"
    />,
    me,
  );
}

describe("ExportButton", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    create.mockReset();
    get.mockReset();
    opened.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("is hidden without export:run or without the read key", () => {
    renderButton(makeMe({ permissions: ["items:read"] }));
    expect(screen.queryByRole("button", { name: /export/i })).toBeNull();
    renderButton(makeMe({ permissions: ["export:run"] }));
    expect(screen.queryByRole("button", { name: /export/i })).toBeNull();
  });

  it("posts the filters, polls every 2 s until done, then downloads a fresh link", async () => {
    create.mockResolvedValue(job("queued"));
    get
      .mockResolvedValueOnce(job("running"))
      .mockResolvedValueOnce(job("done"))
      .mockResolvedValueOnce(job("done", { download_url: "http://s3/f.csv?sig" }));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderButton();
    await user.click(screen.getByRole("button", { name: /export/i }));
    await user.click(screen.getByRole("radio", { name: /xlsx/i }));
    await user.click(screen.getByRole("button", { name: "Export" }));
    expect(create).toHaveBeenCalledWith(
      { resource: "items", format: "xlsx", filters: { q: "plan", "filter[status]": "open" } },
      expect.objectContaining({ headers: { "X-Tenant": "acme" } }),
    );
    expect(get).not.toHaveBeenCalled();
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS)));
    expect(get).toHaveBeenCalledTimes(1);
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS)));
    expect(await screen.findByText(/Ready: 4 rows/)).toBeInTheDocument();
    const result = screen.getByText(/Ready: 4 rows/).closest("[role=status]") as HTMLElement;
    await user.click(within(result).getByRole("button", { name: /download/i }));
    await waitFor(() => expect(opened).toHaveBeenCalledWith("http://s3/f.csv?sig"));
  });

  it("a failed job shows its error and offers to try again", async () => {
    create.mockResolvedValue(job("queued"));
    get.mockResolvedValue(
      job("failed", { error: "5 rows match, the limit is 2; narrow the filters" }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderButton();
    await user.click(screen.getByRole("button", { name: /export/i }));
    await user.click(screen.getByRole("button", { name: "Export" }));
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS)));
    expect(await screen.findByRole("alert")).toHaveTextContent("narrow the filters");
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
  });

  it("closing the dialog stops polling", async () => {
    create.mockResolvedValue(job("queued"));
    get.mockResolvedValue(job("running"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderButton();
    await user.click(screen.getByRole("button", { name: /export/i }));
    await user.click(screen.getByRole("button", { name: "Export" }));
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS)));
    expect(get).toHaveBeenCalledTimes(1);
    await user.click(screen.getAllByRole("button", { name: "Close" })[0]!);
    await act(async () => void (await vi.advanceTimersByTimeAsync(POLL_MS * 5)));
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("lists recent exports; a done one downloads", async () => {
    get.mockResolvedValue(job("done", { id: "old1", download_url: "http://s3/old.csv" }));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderButton();
    await user.click(screen.getByRole("button", { name: /export/i }));
    const recent = screen.getByRole("region", { name: "Recent exports" });
    expect(recent).toHaveTextContent("files · XLSX");
    expect(recent).toHaveTextContent("failed");
    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(opened).toHaveBeenCalledWith("http://s3/old.csv"));
  });

  it("an expired export explains instead of opening a dead link", async () => {
    get.mockResolvedValue(job("expired", { id: "old1" }));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderButton();
    await user.click(screen.getByRole("button", { name: /export/i }));
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("expired");
    expect(opened).not.toHaveBeenCalled();
  });
});
