"use client";
// Client-side providers (object 16): TanStack Query, theme, toasts.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";

import { Toaster } from "@/components/ui/sonner";
import { isApiError } from "@/lib/api-error";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Do not retry HTTP errors (4xx/5xx carry a real answer); retry
        // network failures (status 0) twice.
        retry: (count, err) => !(isApiError(err) && err.status > 0) && count < 2,
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  // One client per browser tab; useState keeps it stable across renders.
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        {children}
        <Toaster richColors closeButton position="top-right" />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
