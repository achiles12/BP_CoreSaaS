// Search page (B10 D7, ui_screens S09).
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeMe } from "@/test/fixtures";
import { router, setPathname, setSearch } from "@/test/next-navigation";
import { renderWithSession } from "@/test/render";

import SearchPage from "./page";

vi.mock("next/navigation", () => import("@/test/next-navigation"));

const searchSpy = vi.fn();
vi.mock("@/api/generated/endpoints/search/search", () => ({
  useSearch: (params: unknown, opts: { query?: { enabled?: boolean } }) => {
    searchSpy(params, opts?.query?.enabled);
    return {
      isPending: false,
      isFetching: false,
      isError: false,
      data: {
        total: 3,
        page: 1,
        page_size: 50,
        items: [
          {
            type: "items",
            id: "i1",
            title: "Quarterly plan",
            snippet: "the quarterly budget",
            score: 1.2,
          },
          { type: "files", id: "f1", title: "quarterly-report.pdf", snippet: null, score: 1.1 },
          { type: "items", id: "i2", title: "Other quarterly", snippet: null, score: 0.5 },
        ],
      },
    };
  },
}));
const downloadSpy = vi.fn();
vi.mock("@/lib/files", () => ({ downloadFile: (...a: unknown[]) => downloadSpy(...a) }));

const me = makeMe({ permissions: ["search:use", "files:read", "items:read"] });

async function renderPage() {
  await act(async () => {
    renderWithSession(
      <Suspense>
        <SearchPage />
      </Suspense>,
      me,
    );
  });
}

describe("Search page", () => {
  beforeEach(() => {
    searchSpy.mockClear();
    router.replace.mockClear();
    setPathname("/search");
  });

  it("groups hits by type and highlights the query", async () => {
    setSearch("q=quarterly");
    await renderPage();
    expect(screen.getByRole("heading", { name: /Items/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Files/ })).toBeInTheDocument();
    expect(screen.getAllByText("quarterly", { selector: "mark" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Quarterly plan/ })).toHaveAttribute(
      "href",
      "/items/i1",
    );
    expect(searchSpy).toHaveBeenLastCalledWith(expect.objectContaining({ q: "quarterly" }), true);
  });

  it("a highlighted file title stays one piece of text (no flex gaps)", async () => {
    setSearch("q=quarterly");
    await renderPage();
    const btn = screen.getByRole("button", { name: /quarterly-report.pdf/ });
    // The title's pieces live in ONE child span, not as separate flex items.
    const spans = Array.from(btn.children).filter((c) => c.tagName === "SPAN");
    expect(spans).toHaveLength(1);
    expect(spans[0]!.textContent).toBe("quarterly-report.pdf");
  });

  it("a file hit downloads", async () => {
    setSearch("q=quarterly");
    await renderPage();
    await userEvent.click(screen.getByRole("button", { name: /quarterly-report.pdf/ }));
    expect(downloadSpy).toHaveBeenCalledWith(me, "f1");
  });

  it("no chips when only one type is readable", async () => {
    setSearch("q=quarterly");
    await act(async () => {
      renderWithSession(
        <Suspense>
          <SearchPage />
        </Suspense>,
        makeMe({ permissions: ["search:use", "items:read"] }),
      );
    });
    expect(screen.queryByRole("button", { name: "Files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Items" })).toBeNull();
  });

  it("a chip writes types= to the URL", async () => {
    setSearch("q=quarterly");
    await renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Items" }));
    expect(router.replace).toHaveBeenCalledWith("/search?q=quarterly&types=items", {
      scroll: false,
    });
  });

  it("typing updates q after the debounce; one character asks for more", async () => {
    setSearch("");
    await renderPage();
    expect(searchSpy).toHaveBeenLastCalledWith(expect.anything(), false);
    expect(screen.getByText(/at least 2 characters/i)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox"), "ab");
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/search?q=ab", { scroll: false }),
    );
  });
});
