import { FileQuestion } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Not found" };

// P12 /404: any unknown URL (HTTP status 404).
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-4 text-center">
      <FileQuestion className="text-muted-foreground size-10" aria-hidden />
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground text-sm">The page you are looking for does not exist.</p>
      <Button asChild>
        <Link href="/home">Back to home</Link>
      </Button>
    </main>
  );
}
