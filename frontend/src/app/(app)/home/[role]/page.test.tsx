// Landing pages: cards per role + wrong-role redirect (C1, B09 D4/D5).
import { act, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeOut } from "@/api/generated/model";
import { makeMe, staffMe } from "@/test/fixtures";
import { router } from "@/test/next-navigation";
import { renderWithSession } from "@/test/render";

import RoleHomePage from "./page";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
// Live cards fetch: return small fixed answers.
vi.mock("@/api/generated/endpoints/files/files", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/files/files")>()),
  useListFiles: (p: { mine?: boolean }) => ({
    isPending: false,
    isError: false,
    data: {
      items: [
        {
          id: "f1",
          name: p?.mine ? "mine.pdf" : "Q3-report.pdf",
          size_bytes: 10,
          created_at: "2026-11-20T00:00:00Z",
        },
      ],
      total: 12,
    },
  }),
}));
vi.mock("@/api/generated/endpoints/users/users", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/users/users")>()),
  useListUsers: () => ({
    isPending: false,
    isError: false,
    data: {
      items: [{ id: "1", email: "a@acme.test", full_name: "A", roles: ["staff"] }],
      total: 7,
    },
  }),
  useListInvitations: () => ({
    isPending: false,
    isError: false,
    data: [
      { id: "i1", email: "p@acme.test", role_key: "user", expired: false },
      { id: "i2", email: "old@acme.test", role_key: "user", expired: true },
    ],
  }),
}));

async function renderRole(role: string, me: MeOut) {
  await act(async () => {
    renderWithSession(
      <Suspense>
        <RoleHomePage params={Promise.resolve({ role })} />
      </Suspense>,
      me,
    );
  });
}

beforeEach(() => router.replace.mockReset());

describe("/home/[role]", () => {
  it("owner sees the owner cards with live data", async () => {
    await renderRole(
      "owner",
      makeMe({ permissions: ["users:read", "users:invite", "files:read", "org:read"] }),
    );
    expect(await screen.findByTestId("landing-title")).toHaveTextContent("Owner dashboard");
    for (const id of [
      "welcome",
      "members",
      "invites",
      "recent-files",
      "activity",
      "org-settings",
    ]) {
      expect(screen.getByTestId(`card-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("members-count")).toHaveTextContent("7");
    expect(screen.getByTestId("invites-count")).toHaveTextContent("1 pending"); // expired one hidden
    expect(screen.getByTestId("card-recent-files")).toHaveTextContent("Q3-report.pdf");
    expect(screen.getByRole("link", { name: /organization settings/i })).toHaveAttribute(
      "href",
      "/settings/organization",
    );
  });

  it("cards are permission-gated: owner without users:invite has no invites card", async () => {
    await renderRole("owner", makeMe({ permissions: ["files:read"] }));
    await screen.findByTestId("landing-title");
    expect(screen.queryByTestId("card-invites")).not.toBeInTheDocument();
    expect(screen.queryByTestId("card-members")).not.toBeInTheDocument();
  });

  it("staff sees welcome, my files and search", async () => {
    await renderRole("staff", staffMe());
    await screen.findByTestId("landing-title");
    expect(screen.getByTestId("card-my-files")).toHaveTextContent("mine.pdf");
    expect(screen.getByRole("search")).toBeInTheDocument();
    expect(screen.queryByTestId("card-team")).not.toBeInTheDocument();
  });

  it("another role's page redirects to the user's own and renders nothing", async () => {
    await renderRole("owner", staffMe());
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/home/staff"));
    expect(screen.queryByTestId("landing-title")).not.toBeInTheDocument();
  });

  it("an unknown role redirects too", async () => {
    await renderRole("ceo", staffMe());
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/home/staff"));
  });
});
