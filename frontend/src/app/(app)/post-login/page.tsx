"use client";
// Post-login (S05, B09 D3): no UI but a spinner. The (app) layout has
// already loaded /me; send the user to `next` or their own landing page.
import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { useSession } from "@/lib/auth";
import { resolvePostLogin } from "@/lib/landing";
import { log } from "@/lib/log";

function Redirect() {
  const { me } = useSession();
  const router = useRouter();
  const next = useSearchParams().get("next");
  useEffect(() => {
    if (!me) return;
    const target = resolvePostLogin(me, next);
    log.info("auth.post_login", { target });
    router.replace(target);
  }, [me, next, router]);
  return (
    <div
      className="text-muted-foreground flex items-center justify-center gap-2 py-24 text-sm"
      aria-busy="true"
    >
      <Loader2 className="size-4 animate-spin" aria-hidden /> Signing you in…
    </div>
  );
}

export default function PostLoginPage() {
  return (
    <Suspense>
      <Redirect />
    </Suspense>
  );
}
