"use client";
// Reset password (S02, B09 D8): token from the emailed link + new password.
// Success revokes every session server-side and clears this browser's
// cookies, so the user logs in again.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { resetPassword } from "@/api/generated/endpoints/auth/auth";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isApiError } from "@/lib/api-error";
import {
  applyServerErrors,
  CONFIRM_MISMATCH,
  newPasswordField,
  PASSWORD_HINT,
  passwordsMatch,
} from "@/lib/forms";
import { log } from "@/lib/log";
import { clearOrg } from "@/lib/org";

const schema = z
  .object({ password: newPasswordField, confirm: z.string() })
  .refine(passwordsMatch, CONFIRM_MISMATCH);
type Values = z.infer<typeof schema>;

export const INVALID_LINK = "This reset link is invalid or has expired.";

function InvalidLink() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Link not valid</CardTitle>
        <CardDescription role="alert">{INVALID_LINK}</CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        <Link href="/forgot-password" className="underline-offset-4 hover:underline">
          Request a new link
        </Link>
      </CardContent>
    </Card>
  );
}

export function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const qc = useQueryClient();
  const [state, setState] = useState<"form" | "done" | "invalid">(token ? "form" : "invalid");
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { password: "", confirm: "" },
  });

  async function onSubmit(values: Values) {
    setFormError(null);
    try {
      await resetPassword({ token, new_password: values.password });
      log.info("auth.password_reset");
      clearOrg();
      qc.clear(); // the backend ended every session, including this one
      setState("done");
    } catch (err) {
      if (isApiError(err) && err.status === 400) {
        setState("invalid");
        return;
      }
      setFormError(applyServerErrors(err, setError, { new_password: "password" }, ["password"]));
    }
  }

  if (state === "invalid") return <InvalidLink />;
  if (state === "done") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle2 className="size-5" aria-hidden /> Password changed
          </CardTitle>
          <CardDescription role="status">
            Your password was changed and you were signed out everywhere.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild className="w-full">
            <Link href="/login">Log in</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Choose a new password</CardTitle>
        <CardDescription>All your other sessions will be signed out.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
          <FormAlert message={formError} />
          <FormField
            id="password"
            label="New password"
            type="password"
            autoComplete="new-password"
            autoFocus
            hint={PASSWORD_HINT}
            error={errors.password?.message}
            {...register("password")}
          />
          <FormField
            id="confirm"
            label="Confirm new password"
            type="password"
            autoComplete="new-password"
            error={errors.confirm?.message}
            {...register("confirm")}
          />
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="size-4 animate-spin" aria-hidden />}
            Change password
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
