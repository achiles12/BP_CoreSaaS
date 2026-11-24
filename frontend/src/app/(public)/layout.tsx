import type { ReactNode } from "react";

import { DevBanner } from "@/components/layout/dev-banner";
import { APP_NAME } from "@/config/site";

// Public layout (ui_screens.md §1): centered card, product name on top.
// B09 object 1 polishes it; the shape stays.
export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className="bg-muted/40 flex min-h-screen flex-col">
      <DevBanner />
      <main className="flex flex-1 flex-col items-center justify-center gap-6 p-4">
        <p className="text-xl font-semibold tracking-tight">{APP_NAME}</p>
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  );
}
