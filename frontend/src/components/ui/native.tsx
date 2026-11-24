// Native form controls styled like shadcn inputs (B10 D15 ruling): a real
// <select>, <textarea>, checkbox and progress bar are accessible by default,
// work with react-hook-form's register() and are trivial to test.
import * as React from "react";

import { cn } from "@/lib/utils";

const FIELD =
  "border-input dark:bg-input/30 w-full rounded-md border bg-transparent px-3 text-base shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive md:text-sm";

function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return <select data-slot="select" className={cn(FIELD, "h-9 py-1", className)} {...props} />;
}

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea data-slot="textarea" className={cn(FIELD, "min-h-24 py-2", className)} {...props} />
  );
}

function Checkbox({ className, ...props }: Omit<React.ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      data-slot="checkbox"
      className={cn("accent-primary size-4 shrink-0 rounded-sm", className)}
      {...props}
    />
  );
}

/** Determinate progress bar, value 0–100. */
function Progress({
  value,
  className,
  label,
}: {
  value: number;
  className?: string;
  label?: string;
}) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={v}
      aria-label={label}
      className={cn("bg-muted h-2 w-full overflow-hidden rounded-full", className)}
    >
      <div className="bg-primary h-full transition-[width]" style={{ width: `${v}%` }} />
    </div>
  );
}

export { Checkbox, NativeSelect, Progress, Textarea };
