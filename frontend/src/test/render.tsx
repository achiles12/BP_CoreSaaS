// Render helper: QueryClient pre-seeded with a /me answer (so useSession()
// resolves synchronously) + next/navigation router mock.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { getMeQueryKey } from "@/api/generated/endpoints/users/users";
import type { MeOut } from "@/api/generated/model";

export function renderWithSession(ui: ReactElement, me?: MeOut) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  if (me) client.setQueryData(getMeQueryKey(), me);
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}
