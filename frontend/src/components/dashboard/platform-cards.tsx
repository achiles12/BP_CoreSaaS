"use client";
// Platform page cards (P07, B09 D14): live data from the B04 platform API.
import { Building2, ShieldCheck, Users } from "lucide-react";

import { usePlatformOrgs, usePlatformStats } from "@/api/generated/endpoints/platform/platform";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { CardError, CardLoading } from "./card-state";

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  icon: typeof Users;
}) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="flex items-center gap-3">
        <Icon className="text-muted-foreground size-5" aria-hidden />
        <div>
          <p className="text-2xl font-semibold">{value}</p>
          <p className="text-muted-foreground text-xs">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function PlatformStatsRow() {
  const q = usePlatformStats();
  if (q.isPending) return <CardLoading rows={2} />;
  if (q.isError) return <CardError error={q.error} />;
  const s = q.data;
  const orgs = Object.values(s.orgs_by_status).reduce((a, b) => a + b, 0);
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="platform-stats">
      <Stat
        label={`Organizations (${s.orgs_by_status.active ?? 0} active)`}
        value={orgs}
        icon={Building2}
      />
      <Stat label="Active users" value={s.users_active} icon={Users} />
      <Stat label="All users" value={s.users_total} icon={Users} />
      <Stat label="Platform admins" value={s.platform_admins} icon={ShieldCheck} />
    </div>
  );
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  active: "default",
  provisioning: "secondary",
  suspended: "outline",
  failed: "destructive",
};

export function OrganizationsTable() {
  const q = usePlatformOrgs();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Organizations</CardTitle>
      </CardHeader>
      <CardContent>
        {q.isPending ? (
          <CardLoading rows={4} />
        ) : q.isError ? (
          <CardError error={q.error} />
        ) : q.data.length === 0 ? (
          <p className="text-muted-foreground text-sm">No organizations yet.</p>
        ) : (
          <Table data-testid="orgs-table">
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Slug</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead className="text-right">Active members</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {q.data.map((o) => (
                <TableRow key={o.id}>
                  <TableCell className="font-medium">{o.name}</TableCell>
                  <TableCell className="font-mono text-xs">{o.slug}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[o.status] ?? "outline"}>{o.status}</Badge>
                  </TableCell>
                  <TableCell>{o.plan}</TableCell>
                  <TableCell className="text-right">{o.members_active}</TableCell>
                  <TableCell>{new Date(o.created_at).toLocaleDateString()}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
