"use client";
// Authenticated app shell (object 8, ui_screens.md §1):
//   top bar: menu button (mobile) · product · org name ......... user menu
//   sidebar (md+) / sheet drawer (mobile) · content
// No org switcher: one organization per user (B04 D1).
import { Menu } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import type { MeOut } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { APP_NAME } from "@/config/site";
import { ownLanding } from "@/lib/landing";

import { DevBanner } from "./dev-banner";
import { SidebarNav } from "./sidebar-nav";
import { NotificationsBell } from "./notifications-bell";
import { UserMenu } from "./user-menu";
import { VerifyBanner } from "./verify-banner";

export function AppShell({ me, children }: { me: MeOut; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const orgLabel = me.org?.name ?? (me.is_platform_admin ? "Platform" : "No organization");
  return (
    <div className="flex min-h-screen flex-col">
      <DevBanner />
      <header className="bg-background sticky top-0 z-30 flex h-14 items-center gap-3 border-b px-4">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="bg-sidebar w-64 p-0">
            <SheetHeader className="border-b">
              <SheetTitle>{APP_NAME}</SheetTitle>
            </SheetHeader>
            <SidebarNav me={me} onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>
        <Link href={ownLanding(me)} className="font-semibold tracking-tight">
          {APP_NAME}
        </Link>
        <Separator orientation="vertical" className="h-5!" />
        <span data-testid="org-name" className="text-muted-foreground truncate text-sm">
          {orgLabel}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <NotificationsBell me={me} />
          <UserMenu me={me} />
        </div>
      </header>
      <VerifyBanner me={me} />
      <div className="flex flex-1">
        <aside className="bg-sidebar hidden w-56 shrink-0 border-r md:block">
          <SidebarNav me={me} />
        </aside>
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
