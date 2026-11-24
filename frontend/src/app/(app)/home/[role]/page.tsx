"use client";
// Role landing pages (P06/S07, B09 D4/D5). One route for the five tenant
// roles; LandingGuard sends anyone else to their own page.
import { use } from "react";

import { LandingGuard } from "@/components/dashboard/landing-guard";
import { LANDING_CARDS } from "@/config/landing";
import { isRoleKey } from "@/lib/landing";
import { filterNav } from "@/lib/permissions";

const TITLES: Record<string, string> = {
  owner: "Owner dashboard",
  admin: "Admin dashboard",
  manager: "Manager dashboard",
  staff: "Staff home",
  user: "Home",
};

export default function RoleHomePage({ params }: { params: Promise<{ role: string }> }) {
  const { role } = use(params);
  return (
    <LandingGuard path={`/home/${role}`}>
      {(me) => {
        const cards = isRoleKey(role) ? filterNav(LANDING_CARDS[role], me) : [];
        return (
          <div className="mx-auto max-w-5xl space-y-6">
            <h1 className="text-2xl font-semibold tracking-tight" data-testid="landing-title">
              {TITLES[role] ?? "Home"}
            </h1>
            <div className="grid gap-4 md:grid-cols-2">
              {cards.map(({ id, component: C }) => (
                <C key={id} me={me} />
              ))}
            </div>
          </div>
        );
      }}
    </LandingGuard>
  );
}
