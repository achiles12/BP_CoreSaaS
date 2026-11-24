"use client";
// One table for every list page (B10 §3.1, D16): skeleton while loading,
// the API's message on error, an empty state, rows with an actions cell.
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { isApiError } from "@/lib/api-error";
import { cn } from "@/lib/utils";

export interface Column<Row> {
  key: string;
  header: ReactNode;
  /** Custom cell; default prints row[key]. */
  cell?: (row: Row) => ReactNode;
  className?: string;
}

const SKELETON_ROWS = 5;

export function errorText(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === "email_not_verified") return "Verify your email to see this.";
    return error.message;
  }
  return "Could not load. Please try again.";
}

export function DataTable<Row>({
  columns,
  rows,
  isLoading = false,
  error,
  empty,
  rowKey,
  rowActions,
  testId,
}: {
  columns: Column<Row>[];
  rows?: Row[];
  isLoading?: boolean;
  error?: unknown;
  empty: ReactNode;
  rowKey: (row: Row) => string;
  rowActions?: (row: Row) => ReactNode;
  testId?: string;
}) {
  if (error) {
    return (
      <p role="alert" className="text-destructive py-6 text-sm">
        {errorText(error)}
      </p>
    );
  }
  if (isLoading || !rows) {
    return (
      <div aria-busy="true" aria-label="Loading" className="space-y-2 py-2">
        {Array.from({ length: SKELETON_ROWS }, (_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return <div className="text-muted-foreground py-10 text-center text-sm">{empty}</div>;
  }
  return (
    <Table data-testid={testId}>
      <TableHeader>
        <TableRow>
          {columns.map((c) => (
            <TableHead key={c.key} className={c.className}>
              {c.header}
            </TableHead>
          ))}
          {rowActions && (
            <TableHead className="w-10">
              <span className="sr-only">Actions</span>
            </TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={rowKey(r)}>
            {columns.map((c) => (
              <TableCell key={c.key} className={cn("max-w-xs truncate", c.className)}>
                {c.cell ? c.cell(r) : String((r as Record<string, unknown>)[c.key] ?? "")}
              </TableCell>
            ))}
            {rowActions && <TableCell className="text-right">{rowActions(r)}</TableCell>}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
