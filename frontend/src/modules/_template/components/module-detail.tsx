"use client";
// Generic module detail (B11, D1/D17): the record's fields with Edit and
// Delete. No history panel: the audit log is read outside the app (D1).
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/data/confirm";
import { errorText } from "@/components/data/data-table";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api-error";
import { useSession } from "@/lib/auth";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";

import type { AnyModuleConfig } from "../types";

export function ModuleDetail({ config, id }: { config: AnyModuleConfig; id: string }) {
  const { me } = useSession();
  const router = useRouter();
  const qc = useQueryClient();
  const [deleting, setDeleting] = useState(false);
  const req = me ? tenantRequest(me) : {};
  const query = config.api.useGet(id, req);
  if (!me) return null;
  const back = (
    <Link href={config.basePath} className="text-primary text-sm hover:underline">
      ← Back to {config.labelPlural.toLowerCase()}
    </Link>
  );

  if (query.isError) {
    return (
      <div className="space-y-3">
        <p role="alert" className="text-destructive text-sm">
          {errorText(query.error)}
        </p>
        {back}
      </div>
    );
  }
  if (query.isPending) return <Skeleton className="h-48 w-full" />;
  const row = query.data;

  async function remove() {
    try {
      await config.api.remove(id, req);
      toast.success(`${config.label} deleted`);
      await qc.invalidateQueries({ queryKey: config.api.listKey });
      router.push(config.basePath);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <>
      {back}
      <PageHeader
        title={config.title(row)}
        actions={
          <>
            {can(me, config.permissions.write) && (
              <Button variant="outline" asChild>
                <Link href={`${config.basePath}/${id}/edit`}>Edit</Link>
              </Button>
            )}
            {can(me, config.permissions.delete) && (
              <Button variant="destructive" onClick={() => setDeleting(true)}>
                Delete
              </Button>
            )}
          </>
        }
      />
      <Card>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[10rem_1fr]">
            {config.detail.map((d) => (
              <div key={d.label} className="contents">
                <dt className="text-muted-foreground text-sm">{d.label}</dt>
                <dd className="text-sm whitespace-pre-wrap">{d.value(row)}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete “${config.title(row)}”?`}
        body={`The ${config.label.toLowerCase()} disappears from lists and search.`}
        confirmLabel="Delete"
        destructive
        onConfirm={remove}
      />
    </>
  );
}
