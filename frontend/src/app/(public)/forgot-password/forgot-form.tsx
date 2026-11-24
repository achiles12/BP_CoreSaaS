"use client";
// Forgot password (S02, B09 D7). The answer is the same whether or not the
// account exists (B03 D8): no account probing.
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, MailCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { forgotPassword } from "@/api/generated/endpoints/auth/auth";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { applyServerErrors, emailField } from "@/lib/forms";
import { log } from "@/lib/log";

const schema = z.object({ email: emailField });
type Values = z.infer<typeof schema>;

export const FORGOT_SENT = "If an account exists for that address, we sent a password reset link.";

export function ForgotForm() {
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: "" } });

  async function onSubmit(values: Values) {
    setFormError(null);
    try {
      await forgotPassword(values);
      log.info("auth.forgot_requested");
      setSentTo(values.email);
    } catch (err) {
      setFormError(applyServerErrors(err, setError, {}, ["email"]));
    }
  }

  if (sentTo) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MailCheck className="size-5" aria-hidden /> Check your email
          </CardTitle>
          <CardDescription role="status">{FORGOT_SENT}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          <p className="text-muted-foreground">The link is valid for one hour.</p>
          <Link href="/login" className="underline-offset-4 hover:underline">
            Back to log in
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Forgot password</CardTitle>
        <CardDescription>Enter your email and we will send you a reset link.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
          <FormAlert message={formError} />
          <FormField
            id="email"
            label="Email"
            type="email"
            autoComplete="email"
            autoFocus
            error={errors.email?.message}
            {...register("email")}
          />
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="size-4 animate-spin" aria-hidden />}
            Send reset link
          </Button>
          <Link
            href="/login"
            className="text-muted-foreground text-center text-sm underline-offset-4 hover:underline"
          >
            Back to log in
          </Link>
        </form>
      </CardContent>
    </Card>
  );
}
