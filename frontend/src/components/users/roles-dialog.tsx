"use client";
// Change a member's roles (wireframe S10, B10 D8): checkboxes over the
// tenant's roles. Rank and last-owner rules are the server's; a refusal is
// shown in the dialog, which stays open.
import { useState } from "react";

import { setUserRoles, useListRoles } from "@/api/generated/endpoints/rbac/rbac";
import type { MemberOut, MeOut } from "@/api/generated/model";
import { FormAlert } from "@/components/forms/form-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/native";
import { errorMessage } from "@/lib/api-error";
import { tenantRequest } from "@/lib/tenant";

interface Props {
  me: MeOut;
  member: MemberOut | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}

/** Keyed by member: each member starts from their own roles, no stale state. */
export function RolesDialog(props: Props) {
  return <RolesDialogInner key={props.member?.id ?? "closed"} {...props} />;
}

function RolesDialogInner({ me, member, onClose, onSaved }: Props) {
  const roles = useListRoles({ request: tenantRequest(me), query: { enabled: member !== null } });
  const [checked, setChecked] = useState<Set<string>>(() => new Set(member?.roles ?? []));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function toggle(key: string) {
    setChecked((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  }

  async function save() {
    if (!member) return;
    setBusy(true);
    setError(null);
    try {
      await setUserRoles(member.id, { role_keys: [...checked].sort() }, tenantRequest(me));
      await onSaved();
      onClose();
    } catch (err) {
      setError(errorMessage(err, "Could not change the roles."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={member !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Roles for {member?.full_name || member?.email}</DialogTitle>
          <DialogDescription>
            A member gets every permission of every role checked.
          </DialogDescription>
        </DialogHeader>
        <FormAlert message={error} />
        <fieldset className="grid gap-2">
          <legend className="sr-only">Roles</legend>
          {(roles.data ?? []).map((r) => (
            <label key={r.key} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={checked.has(r.key)}
                onChange={() => toggle(r.key)}
                aria-label={r.name}
              />
              {r.name}
            </label>
          ))}
        </fieldset>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
