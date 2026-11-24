"use client";
// Route guard, layer 2 (B08 D5, object 10): every page in (app) needs a
// session. /me is the source of truth. A 401 has already been through the
// fetcher's refresh-and-retry; if it still fails, the fetcher emits
// "session expired" and SessionExpiredListener redirects to /login.
import { AlertTriangle } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { SessionExpiredListener } from "@/components/layout/session-expired";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api-error";
import { useSession } from "@/lib/auth";

function ShellSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="flex min-h-screen flex-col">
      <div className="flex h-14 items-center gap-3 border-b px-4">
        <Skeleton className="h-5 w-28" />
        <Skeleton className="h-4 w-20" />
        <Skeleton className="ml-auto size-7 rounded-full" />
      </div>
      <div className="flex flex-1">
        <div className="hidden w-56 space-y-2 border-r p-3 md:block">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
        <div className="flex-1 space-y-3 p-6">
          <Skeleton className="h-7 w-48" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const { me, isLoading, error, refetch } = useSession();

  // C1 "back button does not show data" (B09 D13): a page restored from the
  // back/forward cache after logout would show the old DOM. Reload it, so
  // proxy.ts and /me decide again.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) window.location.reload();
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  let body: ReactNode;
  if (me) {
    body = <AppShell me={me}>{children}</AppShell>;
  } else if (isLoading || (isApiError(error) && error.status === 401)) {
    // 401: the listener is already redirecting to /login; keep the skeleton up.
    body = <ShellSkeleton />;
  } else {
    // Backend down / network error: say so instead of looping redirects.
    const offline = isApiError(error) && error.status === 0;
    body = (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-4 text-center">
        <AlertTriangle className="text-destructive size-8" aria-hidden />
        <p className="text-lg font-medium">
          {offline ? "Cannot reach the server" : "Could not load your session"}
        </p>
        <p className="text-muted-foreground max-w-md text-sm">
          {isApiError(error) ? error.message : "Unexpected error."}
          {isApiError(error) && error.requestId ? ` (request ${error.requestId})` : ""}
        </p>
        <Button onClick={() => void refetch()}>Try again</Button>
      </div>
    );
  }
  return (
    <>
      <SessionExpiredListener />
      {body}
    </>
  );
}
