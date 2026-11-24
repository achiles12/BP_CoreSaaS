// Searchable types the UI knows (B07 search sources), with the read key that
// decides whether a type's chip is shown (the API drops it anyway, B07 D10).
export interface SearchType {
  type: string;
  label: string;
  permission: string;
}

export const SEARCH_TYPES: SearchType[] = [
  { type: "files", label: "Files", permission: "files:read" },
  { type: "items", label: "Items", permission: "items:read" },
];

/** Where an item-like hit opens. Files download instead (D7). */
export const HIT_HREF: Record<string, (id: string) => string> = {
  items: (id) => `/items/${id}`,
};
