"use client";
// "1–25 of 42  ‹ Prev  Next ›" (wireframes S08/S10/S15).
import { Button } from "@/components/ui/button";

export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between gap-2 pt-3 text-sm">
      <span className="text-muted-foreground" data-testid="pager-range">
        {total === 0 ? "0 of 0" : `${from}–${to} of ${total}`}
      </span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ‹ Prev
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= last}
          onClick={() => onPage(page + 1)}
        >
          Next ›
        </Button>
      </div>
    </div>
  );
}
