"use client";
// Listens for the fetcher's "session expired" event (refresh failed) and
// sends the user to /login with a toast (ui_screens.md S16, B08 D13).
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { onSessionExpired } from "@/lib/fetcher";
import { clearOrg } from "@/lib/org";

export const SESSION_EXPIRED_MESSAGE = "Your session has expired. Please log in again.";

export function SessionExpiredListener() {
  const router = useRouter();
  const qc = useQueryClient();
  // Several queries can fail together: handle the first event only.
  const handled = useRef(false);

  useEffect(
    () =>
      onSessionExpired(() => {
        if (handled.current) return;
        handled.current = true;
        toast.warning(SESSION_EXPIRED_MESSAGE, { id: "session-expired" });
        clearOrg();
        qc.clear();
        // Read the URL at event time (not a render-time value) so `next` is current.
        const here = `${window.location.pathname}${window.location.search}`;
        router.replace(`/login?next=${encodeURIComponent(here)}`);
      }),
    [qc, router],
  );
  return null;
}
