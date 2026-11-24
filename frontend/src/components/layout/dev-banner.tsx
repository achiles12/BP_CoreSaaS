"use client";
// Dev-mode banner (ui_screens.md §5, B08 D11). The Mailpit host is taken from
// the address bar so the hint is right on the LAN test PC too.
import { useSyncExternalStore } from "react";

import { APP_ENV, MAILPIT_PORT } from "@/config/site";

const noop = () => () => {};

export function DevBanner({ env = APP_ENV }: { env?: string }) {
  // Server render has no window: fall back to "localhost", then the client value.
  const host = useSyncExternalStore(
    noop,
    () => window.location.hostname,
    () => "localhost",
  );
  if (env !== "dev") return null;
  return (
    <div
      role="note"
      className="bg-warning text-warning-foreground px-4 py-1 text-center text-xs font-medium"
    >
      Dev: emails go to Mailpit ({host}:{MAILPIT_PORT})
    </div>
  );
}
