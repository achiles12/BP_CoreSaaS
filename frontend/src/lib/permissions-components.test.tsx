import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { router } from "@/test/next-navigation";
import { staffMe } from "@/test/fixtures";
import { renderWithSession } from "@/test/render";

import { Can, RequirePermission } from "./permissions";

vi.mock("next/navigation", () => import("@/test/next-navigation"));

describe("<Can> / <RequirePermission>", () => {
  it("<Can> renders children or fallback", () => {
    renderWithSession(
      <>
        <Can perm="files:read">
          <span>yes-files</span>
        </Can>
        <Can perm="users:read" fallback={<span>no-users</span>}>
          <span>yes-users</span>
        </Can>
      </>,
      staffMe(),
    );
    expect(screen.getByText("yes-files")).toBeInTheDocument();
    expect(screen.getByText("no-users")).toBeInTheDocument();
    expect(screen.queryByText("yes-users")).not.toBeInTheDocument();
  });

  it("<RequirePermission> sends a user without the permission to /403", async () => {
    router.replace.mockReset();
    renderWithSession(<RequirePermission perm="users:read">secret</RequirePermission>, staffMe());
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/403"));
  });

  it("<RequirePermission> renders for a user with the permission", () => {
    router.replace.mockReset();
    renderWithSession(<RequirePermission perm="files:read">allowed</RequirePermission>, staffMe());
    expect(screen.getByText("allowed")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });
});
