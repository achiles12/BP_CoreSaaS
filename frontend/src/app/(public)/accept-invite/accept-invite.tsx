"use client";
// Accept invite (S04, B09 D10; backend B04 D8-D10).
//   1. POST /auth/invitation {token} -> org, role, email, existing_account
//   2a. new account:      full name + new password + confirm
//   2b. existing account: CURRENT password only (an invite never sets a password)
//   3. success -> "log in to continue" (accepting does not log in)
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { acceptInvite, invitationInfo } from "@/api/generated/endpoints/auth/auth";
import type { InvitationInfoOut } from "@/api/generated/model";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { Badge } from "@/components/ui/badge";
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

const newSchema = z
  .object({
    full_name: z.string().trim().min(1, "Enter your full name").max(200),
    password: newPasswordField,
    confirm: z.string(),
  })
  .refine(passwordsMatch, CONFIRM_MISMATCH);
const existingSchema = z.object({ password: z.string().min(1, "Enter your current password") });
type Values = { full_name?: string; password: string; confirm?: string };

export const INVALID_INVITE = "This invitation link is invalid, expired or already used.";

function Message({ title, text, alert }: { title: string; text: string; alert?: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription role={alert ? "alert" : "status"}>{text}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button asChild variant="outline" className="w-full">
          <Link href="/login">Go to log in</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function AcceptForm({
  token,
  info,
  onDone,
}: {
  token: string;
  info: InvitationInfoOut;
  onDone: () => void;
}) {
  const existing = info.existing_account;
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(existing ? existingSchema : newSchema) as never,
    defaultValues: { full_name: "", password: "", confirm: "" },
  });

  async function onSubmit(v: Values) {
    setFormError(null);
    try {
      await acceptInvite({ token, password: v.password, full_name: existing ? null : v.full_name });
      log.info("auth.invite_accepted", { existing });
      onDone();
    } catch (err) {
      setFormError(
        applyServerErrors<Values>(
          err,
          setError,
          {},
          existing ? ["password"] : ["full_name", "password"],
        ),
      );
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <FormAlert message={formError} />
      <FormField id="invite-email" label="Email" value={info.email} readOnly disabled />
      {existing ? (
        <FormField
          id="password"
          label="Your current password"
          type="password"
          autoComplete="current-password"
          autoFocus
          hint="You already have an account. Confirm it with your current password."
          error={errors.password?.message}
          {...register("password")}
        />
      ) : (
        <>
          <FormField
            id="full_name"
            label="Full name"
            autoComplete="name"
            autoFocus
            error={errors.full_name?.message}
            {...register("full_name")}
          />
          <FormField
            id="password"
            label="Password"
            type="password"
            autoComplete="new-password"
            hint={PASSWORD_HINT}
            error={errors.password?.message}
            {...register("password")}
          />
          <FormField
            id="confirm"
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            error={errors.confirm?.message}
            {...register("confirm")}
          />
        </>
      )}
      <Button type="submit" disabled={isSubmitting}>
        {isSubmitting && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {existing ? "Join organization" : "Create account and join"}
      </Button>
    </form>
  );
}

export function AcceptInvite() {
  const token = useSearchParams().get("token") ?? "";
  const [info, setInfo] = useState<InvitationInfoOut | null>(null);
  const [state, setState] = useState<"loading" | "form" | "invalid" | "error" | "done">(
    token ? "loading" : "invalid",
  );
  const [error, setErr] = useState("");
  const asked = useRef(false); // StrictMode double effect: ask once

  useEffect(() => {
    if (!token || asked.current) return;
    asked.current = true;
    invitationInfo({ token })
      .then((i) => {
        setInfo(i);
        setState("form");
      })
      .catch((err: unknown) => {
        if (isApiError(err) && err.status === 400) setState("invalid");
        else {
          setErr(isApiError(err) ? err.message : "Unexpected error");
          setState("error");
        }
      });
  }, [token]);

  if (state === "loading") {
    return (
      <Card>
        <CardContent className="text-muted-foreground flex items-center gap-2 py-10 text-sm">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Checking your invitation…
        </CardContent>
      </Card>
    );
  }
  if (state === "invalid")
    return <Message title="Invitation not valid" text={INVALID_INVITE} alert />;
  if (state === "error") return <Message title="Something went wrong" text={error} alert />;
  if (state === "done" && info) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle2 className="size-5" aria-hidden /> You joined {info.org_name}
          </CardTitle>
          <CardDescription role="status">Log in with {info.email} to continue.</CardDescription>
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
        <CardTitle>Join {info!.org_name}</CardTitle>
        <CardDescription>
          You were invited as <Badge variant="secondary">{info!.role_key}</Badge>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <AcceptForm token={token} info={info!} onDone={() => setState("done")} />
      </CardContent>
    </Card>
  );
}
