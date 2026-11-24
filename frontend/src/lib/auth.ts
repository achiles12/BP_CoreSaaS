"use client";
// Session state (B08 D8, object 5).
//
// The session IS the /me query: who the user is, their org, roles,
// permissions and landing path. It is cached by TanStack Query, so every
// component calling useSession() shares one request.
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";

import { logout } from "@/api/generated/endpoints/auth/auth";
import { useMe } from "@/api/generated/endpoints/users/users";
import type { MeOut } from "@/api/generated/model";

import { isApiError } from "./api-error";
import { log } from "./log";
import { clearOrg, setOrg } from "./org";

export type Session = MeOut;

/** Load (or read from cache) the current session. */
export function useSession() {
  const query = useMe({
    // /me is called WITHOUT X-Tenant (B04 D4): the backend uses the user's
    // one org. Sending a stale slug could put a platform admin inside a tenant.
    request: { headers: { "X-Tenant": "" } },
    query: {
      staleTime: 30_000,
      // A 401 here already went through the fetcher's refresh+retry; retrying
      // again would only hammer the API. Network errors get 2 retries.
      retry: (count, err) => !(isApiError(err) && err.status > 0) && count < 2,
      refetchOnWindowFocus: true,
    },
  });

  // Keep the X-Tenant slug in sync with the session org.
  const slug = query.data?.org?.slug ?? null;
  useEffect(() => {
    if (query.isSuccess) setOrg(slug);
  }, [query.isSuccess, slug]);

  return {
    me: query.data,
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
  };
}

/**
 * Log out (B08 D12): revoke the refresh family server-side, then forget all
 * local state. Local state is cleared even if the request fails (offline,
 * already expired): the user asked to leave.
 */
export function useSignOut() {
  const qc = useQueryClient();
  const router = useRouter();
  return useCallback(async () => {
    try {
      await logout();
      log.info("auth.logout");
    } catch (err) {
      log.warn("auth.logout_failed", { err: String(err) });
    } finally {
      clearOrg();
      qc.clear();
      router.replace("/login");
    }
  }, [qc, router]);
}
