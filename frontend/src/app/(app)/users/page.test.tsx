// Users page (B10 D8, ui_screens S10).
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeOut } from "@/api/generated/model";
import { ApiError } from "@/lib/api-error";
import { makeMe } from "@/test/fixtures";
import { router, setPathname, setSearch } from "@/test/next-navigation";
import { renderWithSession } from "@/test/render";

import UsersPage from "./page";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
vi.mock("@/components/exports/export-dialog", () => ({ ExportButton: () => null }));

const listSpy = vi.fn();
const invite = vi.fn();
const revoke = vi.fn();
const deactivate = vi.fn();
const activate = vi.fn();
const setRoles = vi.fn();
const MEMBERS = [
  {
    id: "m1",
    email: "bea@acme.test",
    full_name: "Bea Nine",
    status: "active",
    is_verified: true,
    roles: ["user"],
    joined_at: "2026-11-01T00:00:00Z",
  },
  {
    id: "m2",
    email: "win@acme.test",
    full_name: "Win One",
    status: "inactive",
    is_verified: true,
    roles: ["staff"],
    joined_at: "2026-11-02T00:00:00Z",
  },
];
vi.mock("@/api/generated/endpoints/users/users", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/users/users")>()),
  useListUsers: (p: unknown) => {
    listSpy(p);
    return {
      isPending: false,
      isError: false,
      data: { items: MEMBERS, total: 2, page: 1, page_size: 25 },
    };
  },
  useListInvitations: () => ({
    isPending: false,
    isError: false,
    data: [
      {
        id: "inv1",
        email: "new@acme.test",
        role_key: "staff",
        expired: false,
        created_at: "2026-11-12T00:00:00Z",
        expires_at: "2026-11-19T00:00:00Z",
        invited_by: null,
      },
    ],
  }),
  inviteUser: (...a: unknown[]) => invite(...a),
  revokeInvitation: (...a: unknown[]) => revoke(...a),
  deactivateUser: (...a: unknown[]) => deactivate(...a),
  activateUser: (...a: unknown[]) => activate(...a),
}));
vi.mock("@/api/generated/endpoints/rbac/rbac", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/rbac/rbac")>()),
  useListRoles: () => ({
    data: ["owner", "admin", "manager", "staff", "user"].map((k, i) => ({
      key: k,
      name: k[0]!.toUpperCase() + k.slice(1),
      priority: (i + 1) * 10,
      landing_path: "",
      is_system: true,
      permissions: [],
    })),
  }),
  setUserRoles: (...a: unknown[]) => setRoles(...a),
}));

const ADMIN = ["users:read", "users:invite", "users:deactivate", "roles:read", "roles:assign"];

async function renderAs(me: MeOut) {
  await act(async () => {
    renderWithSession(
      <Suspense>
        <UsersPage />
      </Suspense>,
      me,
    );
  });
}
const openMenu = (name: string) =>
  userEvent.click(screen.getByRole("button", { name: new RegExp(`actions for ${name}`, "i") }));

describe("Users page", () => {
  beforeEach(() => {
    for (const f of [listSpy, invite, revoke, deactivate, activate, setRoles]) f.mockReset();
    router.replace.mockClear();
    setPathname("/users");
    setSearch("");
  });

  it("lists members with role badges and status", async () => {
    await renderAs(makeMe({ permissions: ADMIN }));
    const row = screen.getByRole("row", { name: /Bea Nine/ });
    expect(within(row).getByText("user")).toBeInTheDocument();
    expect(within(row).getByText("active")).toBeInTheDocument();
  });

  it("Status filter goes to the URL and the API", async () => {
    setSearch("status=inactive&q=win");
    await renderAs(makeMe({ permissions: ADMIN }));
    expect(listSpy).toHaveBeenLastCalledWith({
      q: "win",
      "filter[status]": "inactive",
      page: 1,
      page_size: 25,
    });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "active");
    expect(router.replace).toHaveBeenLastCalledWith("/users?status=active&q=win", {
      scroll: false,
    });
  });

  it("manager (read only): no Invite, no invitations tab, no row menu", async () => {
    await renderAs(makeMe({ permissions: ["users:read", "roles:read"] }));
    expect(screen.queryByRole("button", { name: /invite/i })).toBeNull();
    expect(screen.queryByRole("tab", { name: /invitations/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /actions for/i })).toBeNull();
  });

  it("invite sends email + role; a 409 shows the server message", async () => {
    invite.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "conflict", message: "Already a member" }),
    );
    invite.mockResolvedValueOnce({ id: "inv2" });
    await renderAs(makeMe({ permissions: ADMIN }));
    await userEvent.click(screen.getByRole("button", { name: /invite/i }));
    const dlg = screen.getByRole("dialog");
    await userEvent.click(within(dlg).getByRole("button", { name: "Send invite" }));
    expect(await within(dlg).findByText(/enter your email/i)).toBeInTheDocument();
    await userEvent.type(within(dlg).getByLabelText("Email"), "Bea@Acme.test");
    await userEvent.selectOptions(within(dlg).getByLabelText("Role"), "staff");
    await userEvent.click(within(dlg).getByRole("button", { name: "Send invite" }));
    expect(await within(dlg).findByRole("alert")).toHaveTextContent("Already a member");
    expect(invite).toHaveBeenCalledWith(
      { email: "bea@acme.test", role_key: "staff" },
      expect.anything(),
    );
    await userEvent.click(within(dlg).getByRole("button", { name: "Send invite" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("change roles: current roles pre-checked, PUT the new set", async () => {
    setRoles.mockResolvedValue({});
    await renderAs(makeMe({ permissions: ADMIN }));
    await openMenu("Bea Nine");
    await userEvent.click(await screen.findByRole("menuitem", { name: /change roles/i }));
    const dlg = screen.getByRole("dialog");
    expect(within(dlg).getByLabelText("User")).toBeChecked();
    await userEvent.click(within(dlg).getByLabelText("Staff"));
    await userEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(setRoles).toHaveBeenCalledWith(
        "m1",
        { role_keys: ["staff", "user"] },
        expect.anything(),
      ),
    );
  });

  it("roles dialog shows the server's refusal", async () => {
    setRoles.mockRejectedValue(
      new ApiError({
        status: 403,
        code: "permission_denied",
        message: "You cannot assign a role above your own",
      }),
    );
    await renderAs(makeMe({ permissions: ADMIN }));
    await openMenu("Bea Nine");
    await userEvent.click(await screen.findByRole("menuitem", { name: /change roles/i }));
    const dlg = screen.getByRole("dialog");
    await userEvent.click(within(dlg).getByLabelText("Owner"));
    await userEvent.click(within(dlg).getByRole("button", { name: "Save" }));
    expect(await within(dlg).findByRole("alert")).toHaveTextContent("above your own");
  });

  it("deactivate asks first; inactive members get Activate", async () => {
    deactivate.mockResolvedValue({});
    await renderAs(makeMe({ permissions: ADMIN }));
    await openMenu("Bea Nine");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Deactivate" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Deactivate" }),
    );
    await waitFor(() => expect(deactivate).toHaveBeenCalledWith("m1", expect.anything()));
    await openMenu("Win One");
    expect(await screen.findByRole("menuitem", { name: "Activate" })).toBeInTheDocument();
  });

  it("pending invitations tab revokes", async () => {
    revoke.mockResolvedValue(undefined);
    setSearch("tab=invitations");
    await renderAs(makeMe({ permissions: ADMIN }));
    expect(screen.getByRole("tab", { name: /pending invitations \(1\)/i })).toHaveAttribute(
      "data-state",
      "active",
    );
    await userEvent.click(screen.getByRole("button", { name: /revoke/i }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke" }),
    );
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("inv1", expect.anything()));
  });
});
