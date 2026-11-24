// Sidebar menu (B08 D10, object 9; ui_screens.md §1).
//
// An entry shows only if the user passes its gate (lib/permissions.tsx
// filterNav). `soon` entries are pages built in later batches: they render
// disabled with a "soon" badge, so the permission filter can already be seen
// working per role. Since B10 every core page is built; `soon` stays for
// business modules that want to show an entry before their page exists.
import {
  Building2,
  FolderOpen,
  House,
  ListTodo,
  Search,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { Gated } from "@/lib/permissions";

export interface NavItem extends Gated {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Page not built yet (shown disabled). */
  soon?: boolean;
}

export const NAVIGATION: NavItem[] = [
  // "/home" = the user's own landing page (resolved in SidebarNav, B09).
  { label: "Home", href: "/home", icon: House },
  { label: "Files", href: "/files", icon: FolderOpen, permission: "files:read" },
  { label: "Search", href: "/search", icon: Search, permission: "search:use" },
  { label: "Users", href: "/users", icon: Users, permission: "users:read" },
  {
    label: "Organization",
    href: "/settings/organization",
    icon: Building2,
    permission: "org:read",
  },
  // B11 example business module (modules/_template); copy this line with the module.
  { label: "Items", href: "/items", icon: ListTodo, permission: "items:read" },
  { label: "Platform", href: "/platform", icon: ShieldCheck, platformAdmin: true },
];
