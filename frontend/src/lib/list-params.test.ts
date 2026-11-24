// URL <-> list state (B10 D3; review focus 4).
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { router, setPathname, setSearch } from "@/test/next-navigation";

import { toApiParams, useListParams } from "./list-params";

vi.mock("next/navigation", () => import("@/test/next-navigation"));

const DEFAULTS = { q: "", status: "" };

describe("useListParams", () => {
  beforeEach(() => {
    router.replace.mockClear();
    setPathname("/files");
  });

  it("reads values and page from the URL, defaults for the rest", () => {
    setSearch("q=report&page=3");
    const { result } = renderHook(() => useListParams(DEFAULTS));
    expect(result.current.params).toEqual({ q: "report", status: "", page: 3 });
  });

  it.each(["page=abc", "page=-3", "page=0", "page=1.5"])("bad %s -> page 1", (qs) => {
    setSearch(qs);
    const { result } = renderHook(() => useListParams(DEFAULTS));
    expect(result.current.params.page).toBe(1);
  });

  it("set() writes the URL, drops empty values and resets the page", () => {
    setSearch("q=old&page=4&status=open");
    const { result } = renderHook(() => useListParams(DEFAULTS));
    result.current.set({ q: "new" });
    expect(router.replace).toHaveBeenCalledWith("/files?q=new&status=open", { scroll: false });
    result.current.set({ status: "" }); // builds on the first change (URL not updated yet)
    expect(router.replace).toHaveBeenLastCalledWith("/files?q=new", { scroll: false });
  });

  it("set({page}) keeps the filters", () => {
    setSearch("q=x");
    const { result } = renderHook(() => useListParams(DEFAULTS));
    result.current.set({ page: 2 });
    expect(router.replace).toHaveBeenCalledWith("/files?q=x&page=2", { scroll: false });
  });

  it("keeps unknown URL keys (other widgets' state)", () => {
    setSearch("tab=invitations&q=a");
    const { result } = renderHook(() => useListParams(DEFAULTS));
    result.current.set({ q: "b" });
    expect(router.replace).toHaveBeenCalledWith("/files?tab=invitations&q=b", { scroll: false });
  });

  it("two quick changes before the URL updates keep both (walk X5)", () => {
    setSearch("");
    const { result } = renderHook(() => useListParams(DEFAULTS));
    result.current.set({ q: "a" });
    result.current.set({ status: "open" }); // same render: URL not updated yet
    expect(router.replace).toHaveBeenLastCalledWith("/files?q=a&status=open", { scroll: false });
  });

  it("reset() clears the list keys", () => {
    setSearch("q=a&status=open&page=2&tab=x");
    const { result } = renderHook(() => useListParams(DEFAULTS));
    result.current.reset();
    expect(router.replace).toHaveBeenCalledWith("/files?tab=x", { scroll: false });
  });
});

describe("toApiParams", () => {
  it("drops empty strings and keeps page", () => {
    expect(toApiParams({ q: "", status: "open", page: 2 })).toEqual({ status: "open", page: "2" });
  });
});
