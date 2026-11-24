"use client";
// Users + invitations (ui_screens S10, B10 D2, D8). Tabs live in the URL
// (?tab=invitations) next to the list filters.
import { useQueryClient } from "@tanstack/react-query";
import { MailPlus, Power, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  activateUser,
  deactivateUser,
  getListInvitationsQueryKey,
  getListUsersQueryKey,
  revokeInvitation,
  useListInvitations,
  useListUsers,
} from "@/api/generated/endpoints/users/users";
import type { InvitationOut, MemberOut, MeOut } from "@/api/generated/model";
import { ConfirmDialog } from "@/components/data/confirm";
import { DataTable, type Column } from "@/components/data/data-table";
import { Pager } from "@/components/data/pager";
import { RowMenu, type RowMenuItem } from "@/components/data/row-menu";
import { SearchInput } from "@/components/data/search-input";
import { ExportButton } from "@/components/exports/export-dialog";
import { GatedPage, PageHeader } from "@/components/layout/page";
import { InviteDialog } from "@/components/users/invite-dialog";
import { RolesDialog } from "@/components/users/roles-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api-error";
import { formatDate } from "@/lib/format";
import { useListParams } from "@/lib/list-params";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";

const PAGE_SIZE = 25;
const DEFAULTS = { tab: "", q: "", status: "" };

type Pending =
  { kind: "status"; member: MemberOut } | { kind: "revoke"; invitation: InvitationOut } | null;

function UsersBody({ me }: { me: MeOut }) {
  const qc = useQueryClient();
  const { params, set } = useListParams(DEFAULTS);
  const [inviting, setInviting] = useState(false);
  const [editRoles, setEditRoles] = useState<MemberOut | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const canInvite = can(me, "users:invite");
  const canAssign = can(me, "roles:assign");
  const canDeactivate = can(me, "users:deactivate");
  const req = tenantRequest(me);

  const filters: Record<string, string> = {};
  if (params.q) filters.q = params.q;
  if (params.status) filters["filter[status]"] = params.status;
  const members = useListUsers(
    { ...filters, page: params.page, page_size: PAGE_SIZE },
    { request: req },
  );
  const invitations = useListInvitations({ request: req, query: { enabled: canInvite } });
  const pendingInvites = (invitations.data ?? []).filter((i) => !i.expired);

  const refreshMembers = () =>
    qc.invalidateQueries({ queryKey: getListUsersQueryKey().slice(0, 1) });

  async function runPending() {
    if (!pending) return;
    try {
      if (pending.kind === "status") {
        const m = pending.member;
        if (m.status === "active") await deactivateUser(m.id, req);
        else await activateUser(m.id, req);
        toast.success(
          `${m.full_name || m.email} ${m.status === "active" ? "deactivated" : "activated"}`,
        );
        await refreshMembers();
      } else {
        await revokeInvitation(pending.invitation.id, req);
        toast.success(`Invitation for ${pending.invitation.email} revoked`);
        await qc.invalidateQueries({ queryKey: getListInvitationsQueryKey() });
      }
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  const memberColumns: Column<MemberOut>[] = [
    { key: "name", header: "Name", cell: (m) => m.full_name || "—", className: "font-medium" },
    { key: "email", header: "Email" },
    {
      key: "roles",
      header: "Roles",
      cell: (m) => (
        <span className="flex flex-wrap gap-1">
          {m.roles.map((r) => (
            <Badge key={r} variant="outline">
              {r}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (m) => (
        <Badge variant={m.status === "active" ? "default" : "outline"}>{m.status}</Badge>
      ),
    },
  ];

  function memberMenu(m: MemberOut): RowMenuItem[] {
    const items: RowMenuItem[] = [];
    if (canAssign)
      items.push({
        label: "Change roles",
        icon: <ShieldCheck className="size-4" />,
        onSelect: () => setEditRoles(m),
      });
    if (canDeactivate && m.id !== me.user.id) {
      items.push({
        label: m.status === "active" ? "Deactivate" : "Activate",
        icon: <Power className="size-4" />,
        destructive: m.status === "active",
        onSelect: () => setPending({ kind: "status", member: m }),
      });
    }
    return items;
  }

  const memberList = (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <SearchInput
          value={params.q}
          onChange={(v) => set({ q: v })}
          placeholder="Search name or email…"
        />
        <NativeSelect
          aria-label="Status"
          value={params.status}
          onChange={(e) => set({ status: e.target.value })}
          className="w-36"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </NativeSelect>
      </div>
      <DataTable
        testId="members-table"
        columns={memberColumns}
        rows={members.data?.items}
        isLoading={members.isPending}
        error={members.isError ? members.error : undefined}
        rowKey={(m) => m.id}
        empty={params.q || params.status ? "No members match these filters." : "No members yet."}
        rowActions={
          canAssign || canDeactivate
            ? (m) => <RowMenu label={m.full_name || m.email} items={memberMenu(m)} />
            : undefined
        }
      />
      {members.data && members.data.total > 0 && (
        <Pager
          page={params.page}
          pageSize={PAGE_SIZE}
          total={members.data.total}
          onPage={(page) => set({ page })}
        />
      )}
    </div>
  );

  const inviteColumns: Column<InvitationOut>[] = [
    { key: "email", header: "Email", className: "font-medium" },
    { key: "role", header: "Role", cell: (i) => <Badge variant="outline">{i.role_key}</Badge> },
    { key: "sent", header: "Sent", cell: (i) => formatDate(i.created_at) },
    { key: "expires", header: "Expires", cell: (i) => formatDate(i.expires_at) },
  ];

  return (
    <>
      <PageHeader
        title="Users"
        actions={
          <>
            <ExportButton resource="users" filters={filters} readPermission="users:read" />
            {canInvite && (
              <Button onClick={() => setInviting(true)}>
                <MailPlus className="size-4" aria-hidden /> Invite
              </Button>
            )}
          </>
        }
      />
      {canInvite ? (
        <Tabs
          value={params.tab === "invitations" ? "invitations" : "members"}
          onValueChange={(t) => set({ tab: t === "members" ? "" : t })}
        >
          <TabsList>
            <TabsTrigger value="members">
              Members{members.data ? ` (${members.data.total})` : ""}
            </TabsTrigger>
            <TabsTrigger value="invitations">
              Pending invitations ({pendingInvites.length})
            </TabsTrigger>
          </TabsList>
          <TabsContent value="members" className="pt-3">
            {memberList}
          </TabsContent>
          <TabsContent value="invitations" className="pt-3">
            <DataTable
              testId="invitations-table"
              columns={inviteColumns}
              rows={invitations.data ? pendingInvites : undefined}
              isLoading={invitations.isPending}
              error={invitations.isError ? invitations.error : undefined}
              rowKey={(i) => i.id}
              empty="No pending invitations."
              rowActions={(i) => (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPending({ kind: "revoke", invitation: i })}
                  aria-label={`Revoke invitation for ${i.email}`}
                >
                  Revoke
                </Button>
              )}
            />
          </TabsContent>
        </Tabs>
      ) : (
        memberList
      )}

      {canInvite && <InviteDialog me={me} open={inviting} onOpenChange={setInviting} />}
      {canAssign && (
        <RolesDialog
          me={me}
          member={editRoles}
          onClose={() => setEditRoles(null)}
          onSaved={async () => {
            toast.success("Roles updated");
            await refreshMembers();
          }}
        />
      )}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(o) => !o && setPending(null)}
        title={
          pending?.kind === "revoke"
            ? `Revoke the invitation for ${pending.invitation.email}?`
            : pending?.member.status === "active"
              ? `Deactivate ${pending.member.full_name || pending.member.email}?`
              : `Activate ${pending?.kind === "status" ? pending.member.full_name || pending.member.email : ""}?`
        }
        body={
          pending?.kind === "revoke"
            ? "The link in their email stops working."
            : pending?.member.status === "active"
              ? "They are signed out and cannot sign in to this organization until activated again."
              : "They can sign in again with their existing roles."
        }
        confirmLabel={
          pending?.kind === "revoke"
            ? "Revoke"
            : pending?.member.status === "active"
              ? "Deactivate"
              : "Activate"
        }
        destructive={pending?.kind === "revoke" || pending?.member.status === "active"}
        onConfirm={runPending}
      />
    </>
  );
}

export default function UsersPage() {
  return (
    <GatedPage perm="users:read" wide>
      {(me) => <UsersBody me={me} />}
    </GatedPage>
  );
}
