"use client";
// Profile (ui_screens S11, B10 D9): name, read-only email, change password.
// Changing the password signs out every OTHER session (B03 D5); this one stays.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { changePassword } from "@/api/generated/endpoints/auth/auth";
import { getMeQueryKey, updateMe } from "@/api/generated/endpoints/users/users";
import type { MeOut } from "@/api/generated/model";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { GatedPage, PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  CONFIRM_MISMATCH,
  PASSWORD_HINT,
  applyServerErrors,
  newPasswordField,
  passwordsMatch,
} from "@/lib/forms";

const MAX_NAME = 200; // backend MAX_NAME_LEN

const nameSchema = z.object({
  full_name: z
    .string()
    .trim()
    .min(1, "Enter your name")
    .max(MAX_NAME, `At most ${MAX_NAME} characters`),
});
const passwordSchema = z
  .object({
    current: z.string().min(1, "Enter your current password"),
    password: newPasswordField,
    confirm: z.string(),
  })
  .refine(passwordsMatch, CONFIRM_MISMATCH);

function NameForm({ me }: { me: MeOut }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof nameSchema>>({
    resolver: zodResolver(nameSchema),
    defaultValues: { full_name: me.user.full_name ?? "" },
  });
  async function submit(v: z.infer<typeof nameSchema>) {
    setError(null);
    try {
      await updateMe({ full_name: v.full_name });
      await qc.invalidateQueries({ queryKey: getMeQueryKey() });
      toast.success("Name saved");
    } catch (err) {
      setError(applyServerErrors(err, form.setError, {}, ["full_name"]));
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Your details</CardTitle>
      </CardHeader>
      <CardContent>
        <form noValidate onSubmit={form.handleSubmit(submit)} className="grid gap-4">
          <FormAlert message={error} />
          <FormField
            id="profile-name"
            label="Full name"
            autoComplete="name"
            error={form.formState.errors.full_name?.message}
            {...form.register("full_name")}
          />
          <FormField
            id="profile-email"
            label="Email"
            value={me.user.email}
            readOnly
            hint="Your sign-in email cannot be changed here."
          />
          <div>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              Save name
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function PasswordForm() {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const form = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current: "", password: "", confirm: "" },
  });
  const { errors, isSubmitting } = form.formState;
  async function submit(v: z.infer<typeof passwordSchema>) {
    setError(null);
    setDone(false);
    try {
      await changePassword({ current_password: v.current, new_password: v.password });
      form.reset();
      setDone(true);
      toast.success("Password changed");
    } catch (err) {
      setError(
        applyServerErrors(
          err,
          form.setError,
          { new_password: "password", current_password: "current" },
          ["current", "password"],
        ),
      );
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Change password</CardTitle>
        <CardDescription>
          Changing it signs you out on your other devices and browsers; this session stays signed
          in.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form noValidate onSubmit={form.handleSubmit(submit)} className="grid gap-4">
          <FormAlert message={error} />
          {done && (
            <p role="status" className="text-sm">
              Password changed. Your other sessions were signed out.
            </p>
          )}
          <FormField
            id="pw-current"
            label="Current password"
            type="password"
            autoComplete="current-password"
            error={errors.current?.message}
            {...form.register("current")}
          />
          <FormField
            id="pw-new"
            label="New password"
            type="password"
            autoComplete="new-password"
            hint={PASSWORD_HINT}
            error={errors.password?.message}
            {...form.register("password")}
          />
          <FormField
            id="pw-confirm"
            label="Confirm new password"
            type="password"
            autoComplete="new-password"
            error={errors.confirm?.message}
            {...form.register("confirm")}
          />
          <div>
            <Button type="submit" disabled={isSubmitting}>
              Change password
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export default function ProfilePage() {
  return (
    <GatedPage>
      {(me) => (
        <>
          <PageHeader title="Profile" />
          <NameForm me={me} />
          <PasswordForm />
        </>
      )}
    </GatedPage>
  );
}
