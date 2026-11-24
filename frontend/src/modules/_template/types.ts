// The contract between a business module's config and the generic module
// pages (B10/B11 design D13, §3.3). A module supplies a ModuleConfig; the
// generic ModuleList / ModuleDetail / ModuleForm do the rest.
import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { z } from "zod";

import type { Column } from "@/components/data/data-table";

/** A select filter on the list; `param` is both the URL key and the API param. */
export interface FilterSpec {
  param: string;
  label: string;
  options: { value: string; label: string }[];
}

/** One form field. `kind` decides the control. */
export interface FieldSpec {
  name: string;
  label: string;
  kind: "text" | "textarea" | "select";
  options?: { value: string; label: string }[];
  hint?: string;
  maxLength?: number;
}

export interface Page<Row> {
  items: Row[];
  total: number;
  page: number;
  page_size: number;
}

/** Request options as the generated functions take them (X-Tenant header). */
export type Req = RequestInit;

export interface ModuleApi<Row, Create, Update> {
  useList: (params: Record<string, string | number>, req: Req) => UseQueryResult<Page<Row>>;
  /** Must not fetch when `id` is "" (the create form calls it with ""). */
  useGet: (id: string, req: Req) => UseQueryResult<Row>;
  create: (body: Create, req: Req) => Promise<Row>;
  update: (id: string, body: Update, req: Req) => Promise<Row>;
  remove: (id: string, req: Req) => Promise<unknown>;
  /** Query-key prefixes to invalidate after a change. */
  listKey: readonly unknown[];
  getKey: (id: string) => readonly unknown[];
}

export interface ModuleConfig<
  Row extends { id: string },
  Values extends Record<string, string>,
  Create,
  Update,
> {
  /** Export resource name and API resource, e.g. "items". */
  resource: string;
  label: string; // "Item"
  labelPlural: string; // "Items"
  basePath: string; // "/items"
  permissions: { read: string; write: string; delete: string };
  searchPlaceholder: string;
  columns: Column<Row>[];
  filters: FilterSpec[];
  /** Detail page: label + value rows under the title. */
  title: (row: Row) => string;
  detail: { label: string; value: (row: Row) => ReactNode }[];
  /** Form */
  fields: FieldSpec[];
  /** Input and output are the form values (strings). */
  schema: z.ZodType<Values, Values>;
  emptyValues: Values;
  toValues: (row: Row) => Values;
  toCreate: (v: Values) => Create;
  /** Only the fields that changed (PATCH semantics; the API 422s on an empty body). */
  toUpdate: (v: Values, row: Row) => Update;
  api: ModuleApi<Row, Create, Update>;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyModuleConfig = ModuleConfig<any, any, any, any>;
