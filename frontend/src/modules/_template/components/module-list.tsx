"use client";
// Generic module list (B11, design D13): search + the config's filters in
// the URL, the config's columns, paging, New (write permission) and Export.
import { Plus } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { DataTable, type Column } from "@/components/data/data-table";
import { Pager } from "@/components/data/pager";
import { SearchInput } from "@/components/data/search-input";
import { ExportButton } from "@/components/exports/export-dialog";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native";
import { useSession } from "@/lib/auth";
import { toApiParams, useListParams } from "@/lib/list-params";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";

import type { AnyModuleConfig } from "../types";

export const PAGE_SIZE = 25;

export function ModuleList({ config }: { config: AnyModuleConfig }) {
  const { me } = useSession();
  // URL keys: q + every filter param (e.g. "filter[status]"); stable per config.
  const defaults = useMemo(
    () =>
      Object.fromEntries([["q", ""], ...config.filters.map((f) => [f.param, ""])]) as Record<
        string,
        string
      >,
    [config],
  );
  const { params, set } = useListParams(defaults);
  const { page, ...rest } = params;
  const filters = toApiParams(rest);
  const query = config.api.useList(
    { ...filters, page, page_size: PAGE_SIZE },
    me ? tenantRequest(me) : {},
  );
  if (!me) return null;

  // The title cell links to the detail page.
  const columns: Column<{ id: string }>[] = config.columns.map((c, i) =>
    i === 0
      ? {
          ...c,
          cell: (row) => (
            <Link href={`${config.basePath}/${row.id}`} className="hover:underline">
              {c.cell ? c.cell(row) : String((row as Record<string, unknown>)[c.key] ?? "")}
            </Link>
          ),
        }
      : c,
  );
  const filtered = Object.keys(filters).length > 0;

  return (
    <>
      <PageHeader
        title={config.labelPlural}
        actions={
          <>
            <ExportButton
              resource={config.resource}
              filters={filters}
              readPermission={config.permissions.read}
            />
            {can(me, config.permissions.write) && (
              <Button asChild>
                <Link href={`${config.basePath}/new`}>
                  <Plus className="size-4" aria-hidden /> New {config.label.toLowerCase()}
                </Link>
              </Button>
            )}
          </>
        }
      />
      <div className="flex flex-wrap gap-2">
        <SearchInput
          value={params.q ?? ""}
          onChange={(v) => set({ q: v })}
          placeholder={config.searchPlaceholder}
        />
        {config.filters.map((f) => (
          <NativeSelect
            key={f.param}
            aria-label={f.label}
            value={(params as Record<string, string>)[f.param] ?? ""}
            onChange={(e) => set({ [f.param]: e.target.value })}
            className="w-40"
          >
            <option value="">All {f.label.toLowerCase()}</option>
            {f.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
        ))}
      </div>
      <DataTable
        testId={`${config.resource}-table`}
        columns={columns}
        rows={query.data?.items}
        isLoading={query.isPending}
        error={query.isError ? query.error : undefined}
        rowKey={(r) => r.id}
        empty={
          filtered
            ? `No ${config.labelPlural.toLowerCase()} match these filters.`
            : `No ${config.labelPlural.toLowerCase()} yet.`
        }
      />
      {query.data && query.data.total > 0 && (
        <Pager
          page={page}
          pageSize={PAGE_SIZE}
          total={query.data.total}
          // `page` is typed apart from the string filters; the cast bridges the index type.
          onPage={(p) => set({ page: p } as never)}
        />
      )}
    </>
  );
}
