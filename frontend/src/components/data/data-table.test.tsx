// DataTable + Pager states (B10 D16).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";

import { DataTable } from "./data-table";
import { Pager } from "./pager";

type Row = { id: string; name: string };
const COLS = [
  { key: "name", header: "Name" },
  { key: "id", header: "Id", cell: (r: Row) => <code>{r.id.toUpperCase()}</code> },
];

describe("DataTable", () => {
  it("shows a skeleton while loading", () => {
    render(<DataTable columns={COLS} isLoading rowKey={(r: Row) => r.id} empty="none" />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("shows the empty node for no rows", () => {
    render(<DataTable columns={COLS} rows={[]} rowKey={(r: Row) => r.id} empty="No files yet" />);
    expect(screen.getByText("No files yet")).toBeInTheDocument();
  });

  it("shows the API error message", () => {
    const err = new ApiError({ status: 500, code: "internal_error", message: "Boom" });
    render(<DataTable columns={COLS} error={err} rowKey={(r: Row) => r.id} empty="x" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Boom");
  });

  it("renders rows, custom cells and row actions", () => {
    render(
      <DataTable
        columns={COLS}
        rows={[{ id: "a1", name: "Alpha" }]}
        rowKey={(r: Row) => r.id}
        empty="x"
        rowActions={(r: Row) => <button>act {r.name}</button>}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("A1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "act Alpha" })).toBeInTheDocument();
  });
});

describe("Pager", () => {
  it("shows the range and pages", async () => {
    const onPage = vi.fn();
    render(<Pager page={1} pageSize={25} total={42} onPage={onPage} />);
    expect(screen.getByText("1–25 of 42")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /prev/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(onPage).toHaveBeenCalledWith(2);
  });

  it("last page disables Next; zero rows says 0 of 0", () => {
    const { rerender } = render(<Pager page={2} pageSize={25} total={42} onPage={() => {}} />);
    expect(screen.getByText("26–42 of 42")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
    rerender(<Pager page={1} pageSize={25} total={0} onPage={() => {}} />);
    expect(screen.getByText("0 of 0")).toBeInTheDocument();
  });
});
