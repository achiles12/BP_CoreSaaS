"use client";
// Wrong-role redirect (C1, B09 D4): a landing page renders only for the
// user whose /me.landing_path is exactly this path; anyone else is sent to
// their own landing page (or /no-organization).
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import type { MeOut } from "@/api/generated/model";
import { useSession } from "@/lib/auth";
import { ownLanding } from "@/lib/landing";
import { log } from "@/lib/log";

export function LandingGuard({
  path,
  children,
}: {
  path: string;
  children: (me: MeOut) => ReactNode;
}) {
  const { me } = useSession();
  const router = useRouter();
  const mine = me ? ownLanding(me) : null;
  useEffect(() => {
    if (mine && mine !== path) {
      log.info("landing.wrong_role_redirect", { from: path, to: mine });
      router.replace(mine);
    }
  }, [mine, path, router]);
  if (!me || mine !== path) return null;
  return <>{children(me)}</>;
}
