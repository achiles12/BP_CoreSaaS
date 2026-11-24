// Items: the example business module (S15). COPYING: this is the file you
// rewrite for a new module (README.md). Everything below names `items`.
import { createElement } from "react";
import { z } from "zod";

import {
  createItem,
  deleteItem,
  getGetItemQueryKey,
  getListItemsQueryKey,
  updateItem,
  useGetItem,
  useListItems,
} from "@/api/generated/endpoints/items/items";
import type { ItemCreate, ItemOut, ItemUpdate, ListItemsParams } from "@/api/generated/model";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatDateTime } from "@/lib/format";

import type { ModuleConfig, Page } from "./types";

export const ITEM_STATUSES = [
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "done", label: "Done" },
];
const STATUS_LABEL = Object.fromEntries(ITEM_STATUSES.map((s) => [s.value, s.label]));
const MAX_TITLE = 200; // backend MAX_TITLE_LEN
const MAX_DESCRIPTION = 5000;

const statusBadge = (s: string) =>
  createElement(Badge, { variant: s === "done" ? "default" : "outline" }, STATUS_LABEL[s] ?? s);

const schema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Enter a title")
    .max(MAX_TITLE, `At most ${MAX_TITLE} characters`),
  description: z.string().max(MAX_DESCRIPTION, `At most ${MAX_DESCRIPTION} characters`),
  status: z.enum(["open", "in_progress", "done"]),
});
type Values = z.infer<typeof schema>;

export const itemsConfig: ModuleConfig<ItemOut, Values, ItemCreate, ItemUpdate> = {
  resource: "items",
  label: "Item",
  labelPlural: "Items",
  basePath: "/items",
  permissions: { read: "items:read", write: "items:write", delete: "items:delete" },
  searchPlaceholder: "Search items…",
  columns: [
    { key: "title", header: "Title", className: "font-medium" },
    { key: "status", header: "Status", cell: (r) => statusBadge(r.status) },
    { key: "owner", header: "Owner", cell: (r) => r.owner_name ?? "—" },
    { key: "updated", header: "Updated", cell: (r) => formatDate(r.updated_at) },
  ],
  filters: [{ param: "filter[status]", label: "Status", options: ITEM_STATUSES }],
  title: (r) => r.title,
  detail: [
    { label: "Status", value: (r) => statusBadge(r.status) },
    { label: "Owner", value: (r) => r.owner_name ?? "—" },
    { label: "Created", value: (r) => formatDateTime(r.created_at) },
    { label: "Updated", value: (r) => formatDateTime(r.updated_at) },
    {
      label: "Description",
      value: (r) =>
        r.description || createElement("span", { className: "text-muted-foreground" }, "—"),
    },
  ],
  fields: [
    { name: "title", label: "Title", kind: "text", maxLength: MAX_TITLE },
    { name: "description", label: "Description", kind: "textarea", maxLength: MAX_DESCRIPTION },
    { name: "status", label: "Status", kind: "select", options: ITEM_STATUSES },
  ],
  schema: schema as z.ZodType<Values, Values>,
  emptyValues: { title: "", description: "", status: "open" },
  toValues: (r) => ({
    title: r.title,
    description: r.description ?? "",
    status: r.status as Values["status"],
  }),
  toCreate: (v) => ({ title: v.title, description: v.description || null, status: v.status }),
  toUpdate: (v, r) => {
    const out: ItemUpdate = {};
    if (v.title !== r.title) out.title = v.title;
    if ((v.description || null) !== (r.description || null))
      out.description = v.description || null;
    if (v.status !== r.status) out.status = v.status;
    return out;
  },
  api: {
    useList: (params, req) =>
      useListItems(params as ListItemsParams, { request: req }) as ReturnType<
        ModuleConfig<ItemOut, Values, ItemCreate, ItemUpdate>["api"]["useList"]
      >,
    // Idle for "" (the create form shares the hook with edit).
    useGet: (id, req) =>
      useGetItem(id, { request: req, query: { enabled: id !== "" } }) as ReturnType<
        ModuleConfig<ItemOut, Values, ItemCreate, ItemUpdate>["api"]["useGet"]
      >,
    create: (body, req) => createItem(body, req),
    update: (id, body, req) => updateItem(id, body, req),
    remove: (id, req) => deleteItem(id, req),
    listKey: getListItemsQueryKey().slice(0, 1),
    getKey: (id) => getGetItemQueryKey(id),
  },
};

export type ItemsPage = Page<ItemOut>;
