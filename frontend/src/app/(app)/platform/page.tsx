"use client";
// Platform admin landing page (P07, B09 D14).
import { WelcomeCard } from "@/components/dashboard/cards";
import { LandingGuard } from "@/components/dashboard/landing-guard";
import { OrganizationsTable, PlatformStatsRow } from "@/components/dashboard/platform-cards";
import { PLATFORM_PATH } from "@/lib/landing";

export default function PlatformPage() {
  return (
    <LandingGuard path={PLATFORM_PATH}>
      {(me) => (
        <div className="mx-auto max-w-6xl space-y-6">
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="landing-title">
            Platform
          </h1>
          <WelcomeCard me={me} />
          <PlatformStatsRow />
          <OrganizationsTable />
        </div>
      )}
    </LandingGuard>
  );
}
