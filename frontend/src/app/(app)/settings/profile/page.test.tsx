// Profile (B10 D9, ui_screens S11).
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { makeMe } from "@/test/fixtures";
import { renderWithSession } from "@/test/render";

import ProfilePage from "./page";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
const updateMe = vi.fn();
const changePassword = vi.fn();
vi.mock("@/api/generated/endpoints/users/users", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/users/users")>()),
  updateMe: (...a: unknown[]) => updateMe(...a),
}));
vi.mock("@/api/generated/endpoints/auth/auth", async (orig) => ({
  ...(await orig<typeof import("@/api/generated/endpoints/auth/auth")>()),
  changePassword: (...a: unknown[]) => changePassword(...a),
}));

async function renderPage() {
  let client: ReturnType<typeof renderWithSession>["client"];
  await act(async () => {
    client = renderWithSession(<ProfilePage />, makeMe()).client;
  });
  return client!;
}

describe("Profile page", () => {
  beforeEach(() => {
    updateMe.mockReset().mockResolvedValue({});
    changePassword.mockReset().mockResolvedValue(undefined);
  });

  it("shows the email read-only and saves the name", async () => {
    const client = await renderPage();
    const spy = vi.spyOn(client, "invalidateQueries");
    expect(screen.getByLabelText("Email")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Email")).toHaveValue("owner@acme.test");
    const name = screen.getByLabelText("Full name");
    await userEvent.clear(name);
    await userEvent.type(name, "Ada L.");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(updateMe).toHaveBeenCalledWith({ full_name: "Ada L." }));
    expect(spy).toHaveBeenCalled();
  });

  it("checks the new password before sending", async () => {
    await renderPage();
    await userEvent.type(screen.getByLabelText("Current password"), "old-password-123");
    await userEvent.type(screen.getByLabelText("New password"), "short1");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "short2");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText(/at least 12 characters/i)).toBeInTheDocument();
    expect(screen.getByText(/do not match/i)).toBeInTheDocument();
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("a wrong current password is shown; success clears the form", async () => {
    changePassword.mockRejectedValueOnce(
      new ApiError({ status: 400, code: "bad_request", message: "Current password is incorrect" }),
    );
    await renderPage();
    const fill = async () => {
      await userEvent.type(screen.getByLabelText("Current password"), "old-password-123");
      await userEvent.type(screen.getByLabelText("New password"), "new-password-456");
      await userEvent.type(screen.getByLabelText("Confirm new password"), "new-password-456");
      await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    };
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect");
    expect(changePassword).toHaveBeenCalledWith({
      current_password: "old-password-123",
      new_password: "new-password-456",
    });
    await userEvent.clear(screen.getByLabelText("Current password"));
    await userEvent.clear(screen.getByLabelText("New password"));
    await userEvent.clear(screen.getByLabelText("Confirm new password"));
    await fill();
    await waitFor(() => expect(screen.getByLabelText("Current password")).toHaveValue(""));
    expect(screen.getByText(/other sessions/i)).toBeInTheDocument();
  });
});
