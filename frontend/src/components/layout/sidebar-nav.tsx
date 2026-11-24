"use client";
// Sidebar links, filtered by permission (object 8/9, ui_screens.md §1).
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { MeOut } from "@/api/generated/model";
import { Badge } from "@/components/ui/badge";
import { NAVIGATION, type NavItem } from "@/config/navigation";
import { HOME_HREF, ownLanding } from "@/lib/landing";
import { filterNav } from "@/lib/permissions";
import { cn } from "@/lib/utils";

export function SidebarNav({
  me,
  items = NAVIGATION,
  onNavigate,
}: {
  me: MeOut;
  items?: NavItem[];
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const visible = filterNav(items, me);
  // Resolve "Home" to the user's landing page; highlight only the FIRST entry
  // matching the current path (a platform admin's Home and Platform are both /platform).
  const resolve = (href: string) => (href === HOME_HREF ? ownLanding(me) : href);
  const activeKey = visible.find((i) => {
    const h = resolve(i.href);
    return !i.soon && (pathname === h || pathname.startsWith(`${h}/`));
  })?.href;
  return (
    <nav aria-label="Main" className="grid gap-1 p-2">
      {visible.map(({ label, href: rawHref, icon: Icon, soon }) => {
        const href = resolve(rawHref);
        const active = rawHref === activeKey;
        const base = "flex items-center gap-3 rounded-md px-3 py-2 text-sm";
        if (soon) {
          return (
            <span
              key={rawHref}
              aria-disabled="true"
              title="Coming in a later build"
              className={cn(base, "text-muted-foreground cursor-not-allowed")}
            >
              <Icon className="size-4" aria-hidden />
              {label}
              <Badge variant="outline" className="ml-auto text-[10px]">
                soon
              </Badge>
            </span>
          );
        }
        return (
          <Link
            key={rawHref}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              base,
              "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-ring outline-none focus-visible:ring-2",
              active && "bg-sidebar-accent text-sidebar-accent-foreground font-medium",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
