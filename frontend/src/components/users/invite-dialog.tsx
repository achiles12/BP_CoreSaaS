"use client";
// Invite a member (wireframe S10, B10 D8): email + one role. The server
// checks rank and existing membership (409) and its message is shown as is.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useListRoles } from "@/api/generated/endpoints/rbac/rbac";
import { getListInvitationsQueryKey, inviteUser } from "@/api/generated/endpoints/users/users";
import type { MeOut } from "@/api/generated/model";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native";
import { applyServerErrors, emailField } from "@/lib/forms";
import { tenantRequest } from "@/lib/tenant";

const schema = z.object({ email: emailField, role_key: z.string().min(1, "Choose a role") });
type Values = z.infer<typeof schema>;
const DEFAULT_ROLE = "user";

export function InviteDialog({
  me,
  open,
  onOpenChange,
}: {
  me: MeOut;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const qc = useQueryClient();
  const roles = useListRoles({ request: tenantRequest(me), query: { enabled: open } });
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", role_key: DEFAULT_ROLE },
  });
  const { errors, isSubmitting } = form.formState;

  function change(o: boolean) {
    if (!o) {
      form.reset();
      setFormError(null);
    }
    onOpenChange(o);
  }

  async function submit(v: Values) {
    setFormError(null);
    try {
      await inviteUser(v, tenantRequest(me));
      toast.success(`Invitation sent to ${v.email}`);
      await qc.invalidateQueries({ queryKey: getListInvitationsQueryKey() });
      change(false);
    } catch (err) {
      setFormError(applyServerErrors(err, form.setError, {}, ["email", "role_key"]));
    }
  }

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a member</DialogTitle>
          <DialogDescription>They get an email with a link to join.</DialogDescription>
        </DialogHeader>
        <form noValidate onSubmit={form.handleSubmit(submit)} className="grid gap-4">
          <FormAlert message={formError} />
          <FormField
            id="invite-email"
            label="Email"
            type="email"
            autoComplete="off"
            error={errors.email?.message}
            {...form.register("email")}
          />
          <div className="grid gap-2">
            <Label htmlFor="invite-role">Role</Label>
            <NativeSelect id="invite-role" {...form.register("role_key")}>
              {(roles.data ?? [{ key: DEFAULT_ROLE, name: "User" }]).map((r) => (
                <option key={r.key} value={r.key}>
                  {r.name}
                </option>
              ))}
            </NativeSelect>
            {errors.role_key && (
              <p className="text-destructive text-xs">{errors.role_key.message}</p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => change(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              Send invite
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
