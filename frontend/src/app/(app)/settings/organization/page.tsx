"use client";
// Organization settings (ui_screens S12, B10 D10): name and display name,
// editable with org:update (owner by default), read-only otherwise.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { getMeQueryKey } from "@/api/generated/endpoints/users/users";
import {
  getGetOrgQueryKey,
  updateOrg,
  useGetOrg,
} from "@/api/generated/endpoints/organizations/organizations";
import type { MeOut, OrgOut } from "@/api/generated/model";
import { errorText } from "@/components/data/data-table";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { GatedPage, PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { applyServerErrors } from "@/lib/forms";
import { can } from "@/lib/permissions";
import { tenantRequest } from "@/lib/tenant";

const MAX = 200; // backend MAX_ORG_NAME
const schema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(MAX, `At most ${MAX} characters`),
  display_name: z.string().trim().max(MAX, `At most ${MAX} characters`),
});
type Values = z.infer<typeof schema>;

function OrgForm({ me, org }: { me: MeOut; org: OrgOut }) {
  const qc = useQueryClient();
  const editable = can(me, "org:update");
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: org.name, display_name: org.display_name ?? "" },
  });
  useEffect(
    () => form.reset({ name: org.name, display_name: org.display_name ?? "" }),
    [org, form],
  );

  async function submit(v: Values) {
    setError(null);
    try {
      // The API refuses an empty display name: leave it out when blank.
      await updateOrg(
        { name: v.name, ...(v.display_name ? { display_name: v.display_name } : {}) },
        tenantRequest(me),
      );
      await qc.invalidateQueries({ queryKey: getGetOrgQueryKey() });
      await qc.invalidateQueries({ queryKey: getMeQueryKey() }); // org name in the top bar
      toast.success("Organization saved");
    } catch (err) {
      setError(applyServerErrors(err, form.setError, {}, ["name", "display_name"]));
    }
  }

  return (
    <Card>
      <CardContent>
        <form noValidate onSubmit={form.handleSubmit(submit)} className="grid gap-4">
          {!editable && (
            <p className="text-muted-foreground text-sm">
              Only the owner can change these settings.
            </p>
          )}
          <FormAlert message={error} />
          <FormField
            id="org-name"
            label="Name"
            readOnly={!editable}
            error={form.formState.errors.name?.message}
            {...form.register("name")}
          />
          <FormField
            id="org-display"
            label="Display name"
            readOnly={!editable}
            hint="Shown in emails and the top bar when set."
            error={form.formState.errors.display_name?.message}
            {...form.register("display_name")}
          />
          <FormField
            id="org-slug"
            label="Slug"
            value={org.slug}
            readOnly
            hint="Used in the X-Tenant header; cannot be changed."
          />
          {editable && (
            <div>
              <Button type="submit" disabled={form.formState.isSubmitting}>
                Save
              </Button>
            </div>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

function OrgBody({ me }: { me: MeOut }) {
  const q = useGetOrg({ request: tenantRequest(me) });
  return (
    <>
      <PageHeader title="Organization" />
      {q.isError ? (
        <p role="alert" className="text-destructive text-sm">
          {errorText(q.error)}
        </p>
      ) : q.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <OrgForm me={me} org={q.data} />
      )}
    </>
  );
}

export default function OrganizationPage() {
  return <GatedPage perm="org:read">{(me) => <OrgBody me={me} />}</GatedPage>;
}
