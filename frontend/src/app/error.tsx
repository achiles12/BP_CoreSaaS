"use client";
// Route error boundary (S16): an exception while rendering a page shows this
// instead of a blank screen. The digest links the browser error to the
// server log line.
import { AlertTriangle } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { log } from "@/lib/log";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    log.error("ui.route_error", { message: error.message, digest: error.digest });
  }, [error]);
  return (
    <main className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-4 text-center">
      <AlertTriangle className="text-destructive size-10" aria-hidden />
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="text-muted-foreground text-sm">
        An unexpected error occurred{error.digest ? ` (ref ${error.digest})` : ""}.
      </p>
      <Button onClick={reset}>Try again</Button>
    </main>
  );
}
