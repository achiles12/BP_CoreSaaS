"use client";
// List state in the URL (B10 D3, app_flows F8): filters, sort and page live
// in the query string, so a view is shareable and survives reload.
//
// Only the keys named in `defaults` (plus `page`) belong to the list; any
// other key in the URL (e.g. `tab`) is left untouched. Changing a filter
// resets the page to 1, otherwise a narrower filter could land on an empty
// page 7.
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useRef } from "react";

export type ListParams<T extends Record<string, string>> = T & { page: number };

function parsePage(raw: string | null): number {
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 ? n : 1;
}

export function useListParams<T extends Record<string, string>>(defaults: T) {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const keys = useMemo(() => Object.keys(defaults), [defaults]);
  // The query we last asked the router for. router.replace is asynchronous:
  // until the URL catches up, `search` is stale, and a second change made in
  // the meantime (tick "Mine only", then pick a Type) would drop the first.
  // Each change therefore builds on the latest query we wrote.
  const latest = useRef<{ from: string; value: string } | null>(null);
  /** The query to build on: what we last wrote, unless the URL has moved since. */
  const base = useCallback(() => {
    const now = search.toString();
    const l = latest.current;
    return l && l.from === now ? l.value : now;
  }, [search]);

  const params = useMemo(() => {
    const out: Record<string, string | number> = {};
    for (const k of keys) out[k] = search.get(k) ?? defaults[k] ?? "";
    out.page = parsePage(search.get("page"));
    return out as ListParams<T>;
  }, [search, keys, defaults]);

  const write = useCallback(
    (next: URLSearchParams) => {
      const qs = next.toString();
      latest.current = { from: search.toString(), value: qs };
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, search],
  );

  const set = useCallback(
    (patch: Partial<ListParams<T>>) => {
      const next = new URLSearchParams(base());
      const onlyPage = Object.keys(patch).every((k) => k === "page");
      for (const [k, v] of Object.entries(patch)) {
        if (k === "page") continue;
        if (v === "" || v === undefined || v === null) next.delete(k);
        else next.set(k, String(v));
      }
      const page = onlyPage ? Number(patch.page ?? 1) : 1;
      if (page > 1) next.set("page", String(page));
      else next.delete("page");
      write(next);
    },
    [base, write],
  );

  const reset = useCallback(() => {
    const next = new URLSearchParams(base());
    for (const k of [...keys, "page"]) next.delete(k);
    write(next);
  }, [base, keys, write]);

  return { params, set, reset };
}

/** List params -> API query values (strings), without empty ones. */
export function toApiParams(params: Record<string, string | number>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v === "" || v === undefined || v === null) continue;
    out[k] = String(v);
  }
  return out;
}
