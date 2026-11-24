"use client";
// Verify email (S03, B09 D9). POSTs the token ONCE on load: tokens are
// single-use, and StrictMode would otherwise run the effect twice in dev
// (the second call would fail and overwrite the success).
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { verifyEmail } from "@/api/generated/endpoints/auth/auth";
import { getMeQueryKey } from "@/api/generated/endpoints/users/users";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isApiError } from "@/lib/api-error";
import { log } from "@/lib/log";

type State = "working" | "ok" | "invalid" | "error";

export function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const qc = useQueryClient();
  const [state, setState] = useState<State>(token ? "working" : "invalid");
  const [message, setMessage] = useState("");
  const sent = useRef(false);

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;
    verifyEmail({ token })
      .then(() => {
        log.info("auth.email_verified");
        void qc.invalidateQueries({ queryKey: getMeQueryKey() });
        setState("ok");
      })
      .catch((err: unknown) => {
        if (isApiError(err) && err.status === 400) setState("invalid");
        else {
          setMessage(isApiError(err) ? err.message : "Unexpected error");
          setState("error");
        }
      });
  }, [token, qc]);

  if (state === "working") {
    return (
      <Card>
        <CardContent className="text-muted-foreground flex items-center gap-2 py-10 text-sm">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Verifying your email…
        </CardContent>
      </Card>
    );
  }
  const ok = state === "ok";
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {ok ? (
            <CheckCircle2 className="size-5" aria-hidden />
          ) : (
            <XCircle className="text-destructive size-5" aria-hidden />
          )}
          {ok ? "Email verified" : "Could not verify"}
        </CardTitle>
        <CardDescription role={ok ? "status" : "alert"}>
          {ok
            ? "Thank you. Your email address is confirmed."
            : state === "invalid"
              ? "This verification link is invalid or has expired. Log in and use “Resend email” to get a new one."
              : message}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* /post-login works for both: signed in -> landing page; signed out -> login */}
        <Button asChild className="w-full">
          <Link href="/post-login">Continue</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
