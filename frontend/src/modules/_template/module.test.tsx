// B11 module template driven by the items config (design D13, S15, D1, D17).
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeOut } from "@/api/generated/model";
import { ApiError } from "@/lib/api-error";
import { makeMe } from "@/test/fixtures";
import { router, setPathname, setSearch } from "@/test/next-navigation";
import { renderWithSession } from "@/test/render";

import { ModuleDetail } from "./components/module-detail";
import { ModuleForm } from "./components/module-form";
import { ModuleList } from "./components/module-list";
import { itemsConfig } from "./config";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
vi.mock("@/components/exports/export-dialog", () => ({
  ExportButton: ({ filters }: { filters: Record<string, string> }) => (
    <button data-testid="export" data-filters={JSON.stringify(filters)}>
      Export
    </button>
  ),
}));

const ITEM = {
  id: "i1",
  title: "Monthly report run",
  description: "Schedule the monthly report",
  status: "open",
  owner_id: "u1",
  owner_name: "Live Manager",
  created_at: "2026-11-13T09:12:00Z",
  updated_at: "2026-11-13T09:12:00Z",
};
const listSpy = vi.fn();
const create = vi.fn();
const update = vi.fn();
const remove = vi.fn();
let getResult: { isPending: boolean; isError: boolean; data?: unknown; error?: unknown } = {
  isPending: false,
  isError: false,
  data: ITEM,
};
vi.mock("@/api/generated/endpoints/items/items", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/items/items")>()),
  useListItems: (p: unknown) => {
    listSpy(p);
    return {
      isPending: false,
      isError: false,
      data: { items: [ITEM], total: 1, page: 1, page_size: 25 },
    };
  },
  useGetItem: () => getResult,
  createItem: (...a: unknown[]) => create(...a),
  updateItem: (...a: unknown[]) => update(...a),
  deleteItem: (...a: unknown[]) => remove(...a),
}));

const WRITER = makeMe({ permissions: ["items:read", "items:write", "export:run"] });
const READER = makeMe({ permissions: ["items:read"] });
const ADMIN = makeMe({ permissions: ["items:read", "items:write", "items:delete"] });

async function show(ui: ReactElement, me: MeOut) {
  await act(async () => {
    renderWithSession(<Suspense>{ui}</Suspense>, me);
  });
}

describe("ModuleList (items)", () => {
  beforeEach(() => {
    listSpy.mockClear();
    router.replace.mockClear();
    router.push.mockClear();
    setPathname("/items");
    setSearch("");
  });

  it("renders the configured columns; a row opens the detail", async () => {
    await show(<ModuleList config={itemsConfig} />, WRITER);
    expect(screen.getByRole("heading", { name: "Items" })).toBeInTheDocument();
    for (const h of ["Title", "Status", "Owner", "Updated"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Monthly report run" })).toHaveAttribute(
      "href",
      "/items/i1",
    );
  });

  it("filters live in the URL and reach the API and the export", async () => {
    setSearch("q=report&filter%5Bstatus%5D=open");
    await show(<ModuleList config={itemsConfig} />, WRITER);
    expect(listSpy).toHaveBeenLastCalledWith({
      q: "report",
      "filter[status]": "open",
      page: 1,
      page_size: 25,
    });
    expect(JSON.parse(screen.getByTestId("export").dataset.filters!)).toEqual({
      q: "report",
      "filter[status]": "open",
    });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "done");
    expect(router.replace).toHaveBeenLastCalledWith("/items?q=report&filter%5Bstatus%5D=done", {
      scroll: false,
    });
  });

  it("New is shown only with write permission", async () => {
    await show(<ModuleList config={itemsConfig} />, READER);
    expect(screen.queryByRole("link", { name: /new item/i })).toBeNull();
  });
});

describe("ModuleForm (items)", () => {
  beforeEach(() => {
    create.mockReset();
    update.mockReset();
    router.push.mockClear();
    getResult = { isPending: false, isError: false, data: ITEM };
  });

  it("validates title and description length before sending", async () => {
    await show(<ModuleForm config={itemsConfig} mode="create" />, WRITER);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Enter a title")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("create sends the body and opens the new item", async () => {
    create.mockResolvedValue({ ...ITEM, id: "i9" });
    await show(<ModuleForm config={itemsConfig} mode="create" />, WRITER);
    await userEvent.type(screen.getByLabelText("Title"), "New thing");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "in_progress");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        { title: "New thing", description: null, status: "in_progress" },
        expect.objectContaining({ headers: { "X-Tenant": "acme" } }),
      ),
    );
    expect(router.push).toHaveBeenCalledWith("/items/i9");
  });

  it("a server 422 lands on the field", async () => {
    create.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "Request validation failed",
        fields: [{ loc: ["body", "title"], msg: "must not be empty", type: "value_error" }],
      }),
    );
    await show(<ModuleForm config={itemsConfig} mode="create" />, WRITER);
    await userEvent.type(screen.getByLabelText("Title"), "   x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Must not be empty")).toBeInTheDocument();
  });

  it("edit sends only the changed fields", async () => {
    update.mockResolvedValue(ITEM);
    await show(<ModuleForm config={itemsConfig} mode="edit" id="i1" />, WRITER);
    expect(screen.getByLabelText("Title")).toHaveValue("Monthly report run");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "done");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("i1", { status: "done" }, expect.anything()),
    );
    expect(router.push).toHaveBeenCalledWith("/items/i1");
  });

  it("edit without changes does not call the API", async () => {
    await show(<ModuleForm config={itemsConfig} mode="edit" id="i1" />, WRITER);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/nothing changed/i)).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });
});

describe("ModuleDetail (items)", () => {
  beforeEach(() => {
    remove.mockReset().mockResolvedValue(undefined);
    router.push.mockClear();
    getResult = { isPending: false, isError: false, data: ITEM };
  });

  it("shows the fields; Edit/Delete follow permissions; no history panel (D1)", async () => {
    await show(<ModuleDetail config={itemsConfig} id="i1" />, WRITER);
    expect(screen.getByRole("heading", { name: "Monthly report run" })).toBeInTheDocument();
    expect(screen.getByText("Live Manager")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit" })).toHaveAttribute("href", "/items/i1/edit");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByText(/history/i)).toBeNull();
  });

  it("delete asks, deletes, and returns to the list", async () => {
    await show(<ModuleDetail config={itemsConfig} id="i1" />, ADMIN);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() => expect(remove).toHaveBeenCalledWith("i1", expect.anything()));
    expect(router.push).toHaveBeenCalledWith("/items");
  });

  it("a missing item says so", async () => {
    getResult = {
      isPending: false,
      isError: true,
      error: new ApiError({ status: 404, code: "not_found", message: "Item not found" }),
    };
    await show(<ModuleDetail config={itemsConfig} id="nope" />, WRITER);
    expect(screen.getByRole("alert")).toHaveTextContent("Item not found");
    expect(screen.getByRole("link", { name: /back to items/i })).toHaveAttribute("href", "/items");
  });
});
