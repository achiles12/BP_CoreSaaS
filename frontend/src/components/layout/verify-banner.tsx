"use client";
// Unverified-email banner (B09 D6; B03 D1: tenant data needs a verified email).
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { resendVerification } from "@/api/generated/endpoints/auth/auth";
import { getMeQueryKey } from "@/api/generated/endpoints/users/users";
import type { MeOut } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import { isApiError } from "@/lib/api-error";
import { log } from "@/lib/log";

export function VerifyBanner({ me }: { me: MeOut }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  if (me.is_verified) return null;

  async function resend() {
    setBusy(true);
    try {
      await resendVerification();
      log.info("auth.verification_resent");
      toast.success(`Verification email sent to ${me.user.email}`);
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        // already verified meanwhile (e.g. in another tab): refresh the session
        await qc.invalidateQueries({ queryKey: getMeQueryKey() });
      } else if (isApiError(err) && err.status === 429) {
        toast.error(`Too many requests. Try again in ${err.retryAfter ?? 60} s.`);
      } else {
        toast.error(isApiError(err) ? err.message : "Could not send the email");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="status"
      data-testid="verify-banner"
      className="bg-muted flex flex-wrap items-center justify-center gap-3 border-b px-4 py-2 text-sm"
    >
      <span>
        Please verify your email address ({me.user.email}). Some data stays hidden until you do.
      </span>
      <Button size="sm" variant="outline" onClick={() => void resend()} disabled={busy}>
        Resend email
      </Button>
    </div>
  );
}
