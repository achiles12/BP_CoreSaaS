// Organization settings (B10 D10, ui_screens S12).
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeOut } from "@/api/generated/model";
import { makeMe } from "@/test/fixtures";
import { renderWithSession } from "@/test/render";

import OrgPage from "./page";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
const updateOrg = vi.fn();
vi.mock("@/api/generated/endpoints/organizations/organizations", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/organizations/organizations")>()),
  useGetOrg: () => ({
    isPending: false,
    isError: false,
    data: {
      id: "o1",
      slug: "acme",
      name: "Acme Inc",
      display_name: "Acme",
      status: "active",
      plan: "free",
      created_at: "2026-11-01T00:00:00Z",
    },
  }),
  updateOrg: (...a: unknown[]) => updateOrg(...a),
}));

async function renderAs(me: MeOut) {
  await act(async () => {
    renderWithSession(
      <Suspense>
        <OrgPage />
      </Suspense>,
      me,
    );
  });
}

describe("Organization page", () => {
  beforeEach(() => updateOrg.mockReset().mockResolvedValue({}));

  it("owner edits name and display name; slug is read-only", async () => {
    await renderAs(makeMe({ permissions: ["org:read", "org:update"] }));
    expect(screen.getByLabelText("Slug")).toHaveAttribute("readonly");
    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Acme Corp");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(updateOrg).toHaveBeenCalledWith(
        { name: "Acme Corp", display_name: "Acme" },
        expect.anything(),
      ),
    );
  });

  it("without org:update everything is read-only and there is no Save", async () => {
    await renderAs(makeMe({ permissions: ["org:read"] }));
    expect(screen.getByLabelText("Name")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Display name")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByText(/only the owner/i)).toBeInTheDocument();
  });

  it("an empty name is refused before sending", async () => {
    await renderAs(makeMe({ permissions: ["org:read", "org:update"] }));
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/enter a name/i)).toBeInTheDocument();
    expect(updateOrg).not.toHaveBeenCalled();
  });
});
