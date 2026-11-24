"use client";
// Search (ui_screens S09, B10 D7): one big input, type chips, results
// grouped by type with the query words highlighted.
import { FileText, Search as SearchIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useSearch } from "@/api/generated/endpoints/search/search";
import type { MeOut, SearchHit } from "@/api/generated/model";
import { errorText } from "@/components/data/data-table";
import { Pager } from "@/components/data/pager";
import { GatedPage, PageHeader } from "@/components/layout/page";
import { HIT_HREF, SEARCH_TYPES } from "@/components/search/search-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { downloadFile } from "@/lib/files";
import { Highlight } from "@/lib/highlight";
import { useListParams } from "@/lib/list-params";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";

const DEBOUNCE_MS = 300; // app_flows F8
const MIN_Q = 2; // backend MIN_Q_LEN
const PAGE_SIZE = 50;
const DEFAULTS = { q: "", types: "" };

function HitRow({ me, hit, q }: { me: MeOut; hit: SearchHit; q: string }) {
  const href = HIT_HREF[hit.type]?.(hit.id);
  const title = <Highlight text={hit.title} query={q} />;
  return (
    <li className="space-y-1 py-3">
      {href ? (
        <Link href={href} className="font-medium hover:underline">
          {title}
        </Link>
      ) : (
        <button
          type="button"
          className="inline-flex items-center gap-1.5 font-medium hover:underline"
          onClick={() => downloadFile(me, hit.id)}
          title="Download"
        >
          <FileText className="size-4 shrink-0" aria-hidden />
          {/* one inline box: the highlight pieces must not become flex items (gap) */}
          <span>{title}</span>
        </button>
      )}
      {hit.snippet && (
        <p className="text-muted-foreground text-sm">
          <Highlight text={hit.snippet} query={q} />
        </p>
      )}
    </li>
  );
}

function SearchBody({ me }: { me: MeOut }) {
  const { params, set } = useListParams(DEFAULTS);
  const [text, setText] = useState(params.q);
  const readable = SEARCH_TYPES.filter((t) => can(me, t.permission));
  const selected = params.types ? params.types.split(",") : [];

  // Debounce typing into the URL (the URL is the source of truth, D3).
  useEffect(() => {
    if (text.trim() === params.q) return;
    const t = setTimeout(() => set({ q: text.trim() }), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [text, params.q, set]);

  const q = params.q;
  const enabled = q.length >= MIN_Q;
  const query = useSearch(
    {
      q,
      ...(params.types ? { types: params.types } : {}),
      page: params.page,
      page_size: PAGE_SIZE,
    },
    { request: tenantRequest(me), query: { enabled } },
  );

  const groups = useMemo(() => {
    const out = new Map<string, SearchHit[]>();
    for (const h of query.data?.items ?? []) out.set(h.type, [...(out.get(h.type) ?? []), h]);
    return out;
  }, [query.data]);

  function toggle(type: string) {
    const next = selected.includes(type) ? selected.filter((t) => t !== type) : [...selected, type];
    set({ types: next.join(",") });
  }

  return (
    <>
      <PageHeader title="Search" />
      <div className="relative">
        <SearchIcon className="text-muted-foreground absolute top-3 left-3 size-5" aria-hidden />
        <Input
          type="search"
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Search files and records…"
          aria-label="Search"
          className="h-12 pl-11 text-lg md:text-lg"
          maxLength={100}
        />
      </div>
      {readable.length > 1 && (
        <div className="flex flex-wrap gap-2" aria-label="Filter by type">
          {readable.map((t) => (
            <Button
              key={t.type}
              size="sm"
              variant={selected.includes(t.type) ? "default" : "outline"}
              aria-pressed={selected.includes(t.type)}
              onClick={() => toggle(t.type)}
            >
              {t.label}
            </Button>
          ))}
        </div>
      )}

      {!enabled ? (
        <p className="text-muted-foreground text-sm">Type at least 2 characters to search.</p>
      ) : query.isError ? (
        <p role="alert" className="text-destructive text-sm">
          {errorText(query.error)}
        </p>
      ) : query.isPending ? (
        <div aria-busy="true" aria-label="Loading" className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : query.data.total === 0 ? (
        <p className="text-muted-foreground text-sm" data-testid="search-empty">
          Nothing found for “{q}”.
        </p>
      ) : (
        <div className="space-y-6" data-testid="search-results">
          {SEARCH_TYPES.filter((t) => groups.has(t.type)).map((t) => (
            <section key={t.type}>
              <h2 className="text-muted-foreground border-b pb-1 text-sm font-semibold tracking-wide uppercase">
                {t.label} ({groups.get(t.type)!.length})
              </h2>
              <ul className="divide-y">
                {groups.get(t.type)!.map((h) => (
                  <HitRow key={`${h.type}-${h.id}`} me={me} hit={h} q={q} />
                ))}
              </ul>
            </section>
          ))}
          {query.data.total > PAGE_SIZE && (
            <Pager
              page={params.page}
              pageSize={PAGE_SIZE}
              total={query.data.total}
              onPage={(page) => set({ page })}
            />
          )}
        </div>
      )}
    </>
  );
}

export default function SearchPage() {
  return <GatedPage perm="search:use">{(me) => <SearchBody me={me} />}</GatedPage>;
}
