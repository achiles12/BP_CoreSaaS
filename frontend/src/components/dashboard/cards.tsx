"use client";
// Landing-page cards (ui_screens.md S07, B09 D5). Since B10 (D14) the file,
// search, export and shortcut cards are live; only "Recent activity" stays a
// placeholder until a business module feeds it. Permission gating happens in
// config/landing.ts; cards that fetch also handle their own errors.
import {
  Activity,
  Building2,
  Download,
  FolderOpen,
  MailPlus,
  Search,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useListFiles } from "@/api/generated/endpoints/files/files";
import { useListInvitations, useListUsers } from "@/api/generated/endpoints/users/users";
import type { MeOut } from "@/api/generated/model";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { downloadFile } from "@/lib/files";
import { formatDate } from "@/lib/format";
import { tenantRequest } from "@/lib/tenant";
import { cn } from "@/lib/utils";

import { CardError, CardLoading } from "./card-state";

export interface CardProps {
  me: MeOut;
}

function DashCard({
  title,
  icon: Icon,
  description,
  children,
  className,
  testId,
}: {
  title: string;
  icon: LucideIcon;
  description?: ReactNode;
  children?: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <Card className={cn("gap-4", className)} data-testid={testId}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="text-muted-foreground size-4" aria-hidden />
          {title}
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      {children && <CardContent>{children}</CardContent>}
    </Card>
  );
}

/** A card whose content arrives in a later batch. */
function Placeholder({
  title,
  icon,
  batch,
  text,
  testId,
}: {
  title: string;
  icon: LucideIcon;
  batch: string;
  text: string;
  testId: string;
}) {
  return (
    <DashCard title={title} icon={icon} testId={testId}>
      <p className="text-muted-foreground text-sm">{text}</p>
      <Badge variant="outline" className="mt-3">
        arrives in {batch}
      </Badge>
    </DashCard>
  );
}

// ------------------------------------------------------------------ live --
export function WelcomeCard({ me }: CardProps) {
  const name = me.user.full_name || me.user.email;
  return (
    <DashCard
      title={`Welcome, ${name}`}
      icon={Building2}
      className="md:col-span-2"
      testId="card-welcome"
      description={
        me.org ? (
          <>
            {me.org.name} · <span className="font-mono">{me.org.slug}</span>
          </>
        ) : (
          "Platform administration"
        )
      }
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Signed in as {me.user.email}</span>
        {me.roles.map((r) => (
          <Badge key={r}>{r}</Badge>
        ))}
        {me.is_platform_admin && <Badge>platform admin</Badge>}
      </div>
    </DashCard>
  );
}

export function MembersCountCard({ me }: CardProps) {
  const q = useListUsers(
    { status: "active", page: 1, page_size: 1 },
    { request: tenantRequest(me) },
  );
  return (
    <DashCard title="Members" icon={Users} testId="card-members">
      {q.isPending ? (
        <CardLoading rows={1} />
      ) : q.isError ? (
        <CardError error={q.error} />
      ) : (
        <p className="text-3xl font-semibold" data-testid="members-count">
          {q.data.total}
          <span className="text-muted-foreground ml-2 text-sm font-normal">active</span>
        </p>
      )}
    </DashCard>
  );
}

export function PendingInvitesCard({ me }: CardProps) {
  const q = useListInvitations({ request: tenantRequest(me) });
  const pending = q.data?.filter((i) => !i.expired) ?? [];
  return (
    <DashCard title="Pending invites" icon={MailPlus} testId="card-invites">
      {q.isPending ? (
        <CardLoading />
      ) : q.isError ? (
        <CardError error={q.error} />
      ) : pending.length === 0 ? (
        <p className="text-muted-foreground text-sm">No pending invitations.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          <li className="text-muted-foreground text-xs" data-testid="invites-count">
            {pending.length} pending
          </li>
          {pending.slice(0, 5).map((i) => (
            <li key={i.id} className="flex items-center justify-between gap-2">
              <span className="truncate">{i.email}</span>
              <Badge variant="outline">{i.role_key}</Badge>
            </li>
          ))}
        </ul>
      )}
    </DashCard>
  );
}

export function TeamMembersCard({ me }: CardProps) {
  const q = useListUsers(
    { status: "active", page: 1, page_size: 5 },
    { request: tenantRequest(me) },
  );
  return (
    <DashCard title="Team members" icon={Users} testId="card-team">
      {q.isPending ? (
        <CardLoading />
      ) : q.isError ? (
        <CardError error={q.error} />
      ) : (
        <ul className="space-y-2 text-sm">
          {q.data.items.map((m) => (
            <li key={m.id} className="flex items-center justify-between gap-2">
              <span className="truncate">{m.full_name || m.email}</span>
              <span className="flex gap-1">
                {m.roles.map((r) => (
                  <Badge key={r} variant="outline">
                    {r}
                  </Badge>
                ))}
              </span>
            </li>
          ))}
          {q.data.total > q.data.items.length && (
            <li className="text-muted-foreground text-xs">
              and {q.data.total - q.data.items.length} more
            </li>
          )}
        </ul>
      )}
    </DashCard>
  );
}

/** A card that links to a page (B10 D14). */
function LinkCard({
  title,
  icon,
  href,
  text,
  testId,
}: {
  title: string;
  icon: LucideIcon;
  href: string;
  text: string;
  testId: string;
}) {
  return (
    <DashCard title={title} icon={icon} testId={testId}>
      <p className="text-muted-foreground mb-3 text-sm">{text}</p>
      <Link href={href} className="text-primary text-sm font-medium hover:underline">
        Open {title.toLowerCase()} →
      </Link>
    </DashCard>
  );
}
export const ManageUsersShortcut = () => (
  <LinkCard
    title="Manage users"
    icon={Users}
    href="/users"
    testId="card-manage-users"
    text="Invite members, change roles, deactivate accounts."
  />
);
export const OrgSettingsShortcut = () => (
  <LinkCard
    title="Organization settings"
    icon={Building2}
    href="/settings/organization"
    testId="card-org-settings"
    text="Name and display name of your organization."
  />
);

/** Latest files (all, or only mine), each one click from a download. */
function FileListCard({
  me,
  title,
  mine,
  testId,
  empty,
}: CardProps & { title: string; mine: boolean; testId: string; empty: string }) {
  const q = useListFiles(
    { ...(mine ? { mine: true } : {}), page: 1, page_size: 5 },
    { request: tenantRequest(me) },
  );
  return (
    <DashCard title={title} icon={FolderOpen} testId={testId}>
      {q.isPending ? (
        <CardLoading />
      ) : q.isError ? (
        <CardError error={q.error} />
      ) : q.data.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{empty}</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {q.data.items.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-2">
              <button
                type="button"
                className="truncate text-left hover:underline"
                onClick={() => void downloadFile(me, f.id)}
                title="Download"
              >
                {f.name}
              </button>
              <span className="text-muted-foreground shrink-0 text-xs">
                {formatDate(f.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Link
        href={mine ? "/files?mine=1" : "/files"}
        className="text-primary mt-3 inline-block text-sm font-medium hover:underline"
      >
        All files →
      </Link>
    </DashCard>
  );
}

export const RecentFilesCard = ({ me }: CardProps) => (
  <FileListCard
    me={me}
    title="Recent files"
    mine={false}
    testId="card-recent-files"
    empty="No files uploaded yet."
  />
);
export const MyFilesCard = ({ me }: CardProps) => (
  <FileListCard
    me={me}
    title="My recent files"
    mine
    testId="card-my-files"
    empty="You have not uploaded any files yet."
  />
);
export function FilesCard({ me }: CardProps) {
  const q = useListFiles({ page: 1, page_size: 1 }, { request: tenantRequest(me) });
  return (
    <DashCard title="Files" icon={FolderOpen} testId="card-files">
      {q.isPending ? (
        <CardLoading rows={1} />
      ) : q.isError ? (
        <CardError error={q.error} />
      ) : (
        <p className="text-3xl font-semibold">
          {q.data.total}
          <span className="text-muted-foreground ml-2 text-sm font-normal">files</span>
        </p>
      )}
      <Link
        href="/files"
        className="text-primary mt-3 inline-block text-sm font-medium hover:underline"
      >
        Browse files →
      </Link>
    </DashCard>
  );
}
export const ActivityCard = () => (
  <Placeholder
    title="Recent activity"
    icon={Activity}
    batch="a business module"
    testId="card-activity"
    text="Activity from business modules will show here."
  />
);
/** Exports start from a list (S13): link to the lists this user may export. */
export function ExportShortcut({ me }: CardProps) {
  const lists = [
    { href: "/files", label: "Files", perm: "files:read" },
    { href: "/users", label: "Users", perm: "users:read" },
    { href: "/items", label: "Items", perm: "items:read" },
  ].filter((l) => me.permissions.includes(l.perm));
  return (
    <DashCard title="Exports" icon={Download} testId="card-export">
      <p className="text-muted-foreground mb-3 text-sm">
        Open a list, filter it, then use Export for CSV or Excel.
      </p>
      <div className="flex flex-wrap gap-3 text-sm">
        {lists.map((l) => (
          <Link key={l.href} href={l.href} className="text-primary font-medium hover:underline">
            {l.label} →
          </Link>
        ))}
      </div>
    </DashCard>
  );
}
export function SearchBoxCard() {
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <DashCard title="Search" icon={Search} testId="card-search">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          const t = q.trim();
          router.push(t ? `/search?q=${encodeURIComponent(t)}` : "/search");
        }}
      >
        <Input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search files and records…"
          aria-label="Search files and records"
          maxLength={100}
        />
      </form>
    </DashCard>
  );
}
