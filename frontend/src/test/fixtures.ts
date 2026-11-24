// Shared /me fixtures for component and helper tests.
import type { MeOut } from "@/api/generated/model";

export function makeMe(over: Partial<MeOut> = {}): MeOut {
  return {
    user: {
      id: "u1",
      email: "owner@acme.test",
      full_name: "Ada Owner",
      is_verified: true,
      is_platform_admin: false,
    },
    org: { id: "o1", slug: "acme", name: "Acme Inc" },
    roles: ["owner"],
    permissions: ["files:read", "search:use", "users:read", "org:read", "org:update"],
    landing_path: "/home/owner",
    is_platform_admin: false,
    is_verified: true,
    ...over,
  };
}

/** Staff: no users:read. */
export const staffMe = () =>
  makeMe({
    roles: ["staff"],
    permissions: ["files:read", "search:use", "org:read"],
    landing_path: "/home/staff",
  });

/** Platform admin without an org (B04 D13/D15). */
export const platformMe = () =>
  makeMe({
    user: {
      id: "p1",
      email: "admin@platform.test",
      full_name: null,
      is_verified: true,
      is_platform_admin: true,
    },
    org: null,
    roles: [],
    permissions: [],
    landing_path: "/platform",
    is_platform_admin: true,
  });

export function jsonResponse(status: number, body?: unknown, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}
