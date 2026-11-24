// Which cards each role's landing page shows (ui_screens.md S07, B09 D5).
// A card renders only if the user passes its gate (lib/permissions.tsx
// filterNav). Business modules add their cards here.
import type { ComponentType } from "react";

import {
  ActivityCard,
  ExportShortcut,
  FilesCard,
  ManageUsersShortcut,
  MembersCountCard,
  MyFilesCard,
  OrgSettingsShortcut,
  PendingInvitesCard,
  RecentFilesCard,
  SearchBoxCard,
  TeamMembersCard,
  WelcomeCard,
  type CardProps,
} from "@/components/dashboard/cards";
import type { RoleKey } from "@/lib/landing";
import type { Gated } from "@/lib/permissions";

export interface LandingCard extends Gated {
  id: string;
  component: ComponentType<CardProps>;
}

const welcome: LandingCard = { id: "welcome", component: WelcomeCard };
const recentFiles: LandingCard = {
  id: "recent-files",
  component: RecentFilesCard,
  permission: "files:read",
};
const invites: LandingCard = {
  id: "invites",
  component: PendingInvitesCard,
  permission: "users:invite",
};
const search: LandingCard = { id: "search", component: SearchBoxCard, permission: "search:use" };

export const LANDING_CARDS: Record<RoleKey, LandingCard[]> = {
  owner: [
    welcome,
    { id: "members", component: MembersCountCard, permission: "users:read" },
    invites,
    recentFiles,
    { id: "activity", component: ActivityCard },
    { id: "org-settings", component: OrgSettingsShortcut, permission: "org:read" },
  ],
  admin: [
    welcome,
    invites,
    recentFiles,
    { id: "manage-users", component: ManageUsersShortcut, permission: "users:read" },
  ],
  manager: [
    welcome,
    { id: "team", component: TeamMembersCard, permission: "users:read" },
    recentFiles,
    { id: "export", component: ExportShortcut, permission: "export:run" },
  ],
  staff: [welcome, { id: "my-files", component: MyFilesCard, permission: "files:read" }, search],
  user: [welcome, search, { id: "files", component: FilesCard, permission: "files:read" }],
};
