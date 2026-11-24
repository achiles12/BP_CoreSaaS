import { ShieldX } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "No access" };

// P12 /403 (ui_screens.md S16). Reached via <RequirePermission>.
export default function ForbiddenPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-4 text-center">
      <ShieldX className="text-muted-foreground size-10" aria-hidden />
      <h1 className="text-2xl font-semibold">You do not have access</h1>
      <p className="text-muted-foreground max-w-md text-sm">
        Your role does not include the permission this page needs. Ask an administrator if you think
        this is wrong.
      </p>
      <Button asChild>
        <Link href="/home">Back to home</Link>
      </Button>
    </main>
  );
}
