"use client";
// Login (S01, B09 D2). Replaces the B08 placeholder; keeps its silent
// refresh (B08 D6) and error texts. Success -> /post-login, which picks the
// landing page (D3); ?next= is passed through.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { login } from "@/api/generated/endpoints/auth/auth";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isApiError } from "@/lib/api-error";
import { refreshOnce } from "@/lib/fetcher";
import { emailField } from "@/lib/forms";
import { POST_LOGIN_PATH } from "@/lib/landing";
import { log } from "@/lib/log";
import { clearOrg } from "@/lib/org";
import { safeNext } from "@/lib/utils";

const schema = z.object({
  email: emailField,
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

/** User-facing text for a failed login (generic on 401: no account probing). */
export function loginErrorMessage(err: unknown): string {
  if (!isApiError(err)) return "Something went wrong. Please try again.";
  switch (err.status) {
    case 0:
      return "Cannot reach the server. Check your connection.";
    case 401:
      return "Invalid email or password.";
    case 422:
      return "Enter a valid email and password.";
    case 429:
      return err.retryAfter
        ? `Too many attempts. Try again in ${err.retryAfter} s.`
        : "Too many attempts. Try again in a minute.";
    default:
      return err.message;
  }
}

/** /post-login, carrying a safe ?next= along. */
export function postLoginUrl(next: string | null): string {
  const safe = safeNext(next, "");
  return safe ? `${POST_LOGIN_PATH}?next=${encodeURIComponent(safe)}` : POST_LOGIN_PATH;
}

export function LoginForm() {
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const target = postLoginUrl(params.get("next"));

  // "checking" while the silent refresh runs (B08 D6), then "form".
  const [phase, setPhase] = useState<"checking" | "form">("checking");
  const [formError, setFormError] = useState<string | null>(null);
  const tried = useRef(false); // StrictMode runs effects twice in dev: refresh only once
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  useEffect(() => {
    if (tried.current) return;
    tried.current = true;
    refreshOnce().then((ok) => {
      if (ok) {
        log.info("auth.silent_refresh_ok");
        router.replace(target);
      } else {
        setPhase("form");
      }
    });
  }, [target, router]);

  async function onSubmit(values: Values) {
    setFormError(null);
    try {
      clearOrg(); // never carry another account's org slug into this session
      qc.clear();
      await login(values);
      log.info("auth.login_ok");
      router.replace(target);
    } catch (err) {
      log.warn("auth.login_failed", {
        status: isApiError(err) ? err.status : undefined,
        code: isApiError(err) ? err.code : undefined,
      });
      setFormError(loginErrorMessage(err));
    }
  }

  if (phase === "checking") {
    return (
      <Card>
        <CardContent className="text-muted-foreground flex items-center gap-2 py-10 text-sm">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Checking your session…
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Log in</CardTitle>
        <CardDescription>Use your work email and password.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
          <FormAlert message={formError} />
          <FormField
            id="email"
            label="Email"
            type="email"
            autoComplete="username"
            autoFocus
            error={errors.email?.message}
            {...register("email")}
          />
          <div className="grid gap-1">
            <FormField
              id="password"
              label="Password"
              type="password"
              autoComplete="current-password"
              error={errors.password?.message}
              {...register("password")}
            />
            <Link
              href="/forgot-password"
              className="text-muted-foreground justify-self-end text-xs underline-offset-4 hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="size-4 animate-spin" aria-hidden />}
            Log in
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
