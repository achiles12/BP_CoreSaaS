// Files page (B10 D4–D6, ui_screens S08; review focus 5).
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeOut } from "@/api/generated/model";
import { makeMe } from "@/test/fixtures";
import { router, setPathname, setSearch } from "@/test/next-navigation";
import { renderWithSession } from "@/test/render";

import FilesPage from "./page";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
const listSpy = vi.fn();
const deleteSpy = vi.fn();
let rows: unknown[] = [];
vi.mock("@/api/generated/endpoints/files/files", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/files/files")>()),
  useListFiles: (params: unknown) => {
    listSpy(params);
    return {
      isPending: false,
      isError: false,
      data: { items: rows, total: rows.length, page: 1, page_size: 25 },
    };
  },
  deleteFile: (...a: unknown[]) => deleteSpy(...a),
}));
vi.mock("@/components/exports/export-dialog", () => ({
  ExportButton: ({ resource, filters }: { resource: string; filters: Record<string, string> }) => (
    <button data-testid="export" data-filters={JSON.stringify(filters)}>
      Export {resource}
    </button>
  ),
}));

const FILE = {
  id: "f1",
  name: "Q3-report.pdf",
  mime_type: "application/pdf",
  size_bytes: 1_258_291,
  status: "active",
  uploaded_by: "u2",
  uploader_name: "Bea Nine",
  created_at: "2026-11-12T10:00:00Z",
};
const ALL = ["files:read", "files:write", "files:delete", "export:run"];

async function renderAs(me: MeOut) {
  await act(async () => {
    renderWithSession(
      <Suspense>
        <FilesPage />
      </Suspense>,
      me,
    );
  });
}

describe("Files page", () => {
  beforeEach(() => {
    rows = [FILE];
    listSpy.mockClear();
    deleteSpy.mockReset().mockResolvedValue(undefined);
    router.replace.mockClear();
    setPathname("/files");
    setSearch("");
  });

  it("lists files with formatted cells", async () => {
    await renderAs(makeMe({ permissions: ALL }));
    const row = screen.getByRole("row", { name: /Q3-report.pdf/ });
    expect(within(row).getByText("1.2 MB")).toBeInTheDocument();
    expect(within(row).getByText("PDF")).toBeInTheDocument();
    expect(within(row).getByText("Bea Nine")).toBeInTheDocument();
  });

  it("URL filters become API params", async () => {
    setSearch("q=rep&type=pdf&mine=1&from=2026-11-01&to=2026-11-30&page=2");
    await renderAs(makeMe({ permissions: ALL }));
    expect(listSpy).toHaveBeenLastCalledWith({
      q: "rep",
      "filter[mime_type]": "application/pdf",
      mine: true,
      "filter[created_at][gte]": "2026-11-01",
      "filter[created_at][lte]": "2026-11-30",
      page: 2,
      page_size: 25,
    });
    // the export gets the same filters, as strings (B07)
    expect(JSON.parse(screen.getByTestId("export").dataset.filters!)).toEqual({
      q: "rep",
      "filter[mime_type]": "application/pdf",
      mine: "true",
      "filter[created_at][gte]": "2026-11-01",
      "filter[created_at][lte]": "2026-11-30",
    });
  });

  it("Type and Mine only write the URL", async () => {
    await renderAs(makeMe({ permissions: ALL }));
    await userEvent.selectOptions(screen.getByLabelText("Type"), "image");
    expect(router.replace).toHaveBeenLastCalledWith("/files?type=image", { scroll: false });
    await userEvent.click(screen.getByLabelText("Mine only"));
    // both survive: the second change builds on the first (walk X5)
    expect(router.replace).toHaveBeenLastCalledWith("/files?type=image&mine=1", { scroll: false });
  });

  it("read-only user: no Upload, no Delete, no Export", async () => {
    await renderAs(makeMe({ permissions: ["files:read"] }));
    expect(screen.queryByRole("button", { name: /upload/i })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /actions for Q3-report.pdf/i }));
    expect(await screen.findByRole("menuitem", { name: /download/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /delete/i })).toBeNull();
  });

  it("delete asks first, then calls the API", async () => {
    await renderAs(makeMe({ permissions: ALL }));
    await userEvent.click(screen.getByRole("button", { name: /actions for Q3-report.pdf/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete/i }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Delete “Q3-report.pdf”?");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith("f1", expect.anything()));
  });

  it("empty state offers an upload", async () => {
    rows = [];
    await renderAs(makeMe({ permissions: ALL }));
    expect(screen.getByText("No files yet")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /upload/i }).length).toBe(2);
  });

  it("empty with filters says no results", async () => {
    rows = [];
    setSearch("q=zzz");
    await renderAs(makeMe({ permissions: ALL }));
    expect(screen.getByText(/No files match/)).toBeInTheDocument();
  });
});
