// Request options that pin X-Tenant to the session org (B09 D5).
// Cards pass this explicitly instead of relying on the org store, so the
// very first query after /me loads already carries the header (child
// effects run before the parent effect that updates the store).
import type { MeOut } from "@/api/generated/model";

import { TENANT_HEADER } from "./fetcher";

export function tenantRequest(me: Pick<MeOut, "org">): RequestInit {
  return me.org ? { headers: { [TENANT_HEADER]: me.org.slug } } : {};
}
