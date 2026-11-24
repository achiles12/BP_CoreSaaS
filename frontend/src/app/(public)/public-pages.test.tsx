// Forgot / reset / verify / accept-invite pages (B09 D7-D10) with the API mocked.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { setSearch } from "@/test/next-navigation";

import { AcceptInvite, INVALID_INVITE } from "./accept-invite/accept-invite";
import { FORGOT_SENT, ForgotForm } from "./forgot-password/forgot-form";
import { INVALID_LINK, ResetForm } from "./reset-password/reset-form";
import { VerifyEmail } from "./verify-email/verify-email";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
const api = {
  forgotPassword: vi.fn(),
  resetPassword: vi.fn(),
  verifyEmail: vi.fn(),
  invitationInfo: vi.fn(),
  acceptInvite: vi.fn(),
};
vi.mock("@/api/generated/endpoints/auth/auth", () => ({
  forgotPassword: (...a: unknown[]) => api.forgotPassword(...a),
  resetPassword: (...a: unknown[]) => api.resetPassword(...a),
  verifyEmail: (...a: unknown[]) => api.verifyEmail(...a),
  invitationInfo: (...a: unknown[]) => api.invitationInfo(...a),
  acceptInvite: (...a: unknown[]) => api.acceptInvite(...a),
}));

const r = (ui: ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
const bad = (status: number, message = "Invalid or expired token", extra = {}) =>
  new ApiError({ status, code: "x", message, ...extra });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  setSearch("");
  vi.spyOn(console, "info").mockImplementation(() => {});
});

describe("forgot password", () => {
  it("always shows the same confirmation", async () => {
    api.forgotPassword.mockResolvedValue({ status: "accepted" });
    r(<ForgotForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "Nobody@Example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("status")).toHaveTextContent(FORGOT_SENT);
    expect(api.forgotPassword).toHaveBeenCalledWith({ email: "nobody@example.com" });
  });

  it("shows the rate-limit message", async () => {
    api.forgotPassword.mockRejectedValue(bad(429, "", { retryAfter: 30 }));
    r(<ForgotForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 30 s");
  });
});

describe("reset password", () => {
  it("no token -> invalid link", () => {
    r(<ResetForm />);
    expect(screen.getByRole("alert")).toHaveTextContent(INVALID_LINK);
  });

  it("checks strength and confirmation before calling the API", async () => {
    setSearch("token=tok");
    r(<ResetForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("Confirm new password"), "other");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("Use at least 12 characters")).toBeInTheDocument();
    expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
    expect(api.resetPassword).not.toHaveBeenCalled();
  });

  it("success -> 'Password changed' with a login link", async () => {
    setSearch("token=tok");
    api.resetPassword.mockResolvedValue(undefined);
    r(<ResetForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "newpassword123");
    await user.type(screen.getByLabelText("Confirm new password"), "newpassword123");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    expect(api.resetPassword).toHaveBeenCalledWith({
      token: "tok",
      new_password: "newpassword123",
    });
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
  });

  it("expired token (400) -> invalid link page", async () => {
    setSearch("token=old");
    api.resetPassword.mockRejectedValue(bad(400));
    r(<ResetForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "newpassword123");
    await user.type(screen.getByLabelText("Confirm new password"), "newpassword123");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText(INVALID_LINK)).toBeInTheDocument();
  });
});

describe("verify email", () => {
  it("posts the token once and shows success", async () => {
    setSearch("token=v1");
    api.verifyEmail.mockResolvedValue({ status: "verified" });
    r(<VerifyEmail />);
    expect(await screen.findByText("Email verified")).toBeInTheDocument();
    expect(api.verifyEmail).toHaveBeenCalledTimes(1);
    expect(api.verifyEmail).toHaveBeenCalledWith({ token: "v1" });
  });

  it("invalid token -> failure message", async () => {
    setSearch("token=bad");
    api.verifyEmail.mockRejectedValue(bad(400));
    r(<VerifyEmail />);
    expect(await screen.findByText("Could not verify")).toBeInTheDocument();
  });
});

describe("accept invite", () => {
  const info = (existing: boolean) => ({
    email: "new@acme.test",
    org_name: "Acme Inc",
    role_key: "staff",
    existing_account: existing,
  });

  it("invalid token -> message", async () => {
    setSearch("token=bad");
    api.invitationInfo.mockRejectedValue(bad(400));
    r(<AcceptInvite />);
    expect(await screen.findByText(INVALID_INVITE)).toBeInTheDocument();
  });

  it("new account: name + password + confirm, then 'log in'", async () => {
    setSearch("token=inv");
    api.invitationInfo.mockResolvedValue(info(false));
    api.acceptInvite.mockResolvedValue({ status: "accepted", email: "new@acme.test" });
    r(<AcceptInvite />);
    expect(await screen.findByText("Join Acme Inc")).toBeInTheDocument();
    expect(screen.getByText("staff")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Full name"), "Nina New");
    await user.type(screen.getByLabelText("Password"), "invitepass1234");
    await user.type(screen.getByLabelText("Confirm password"), "invitepass1234");
    await user.click(screen.getByRole("button", { name: "Create account and join" }));
    expect(await screen.findByText("You joined Acme Inc")).toBeInTheDocument();
    expect(api.acceptInvite).toHaveBeenCalledWith({
      token: "inv",
      password: "invitepass1234",
      full_name: "Nina New",
    });
    expect(api.invitationInfo).toHaveBeenCalledTimes(1);
  });

  it("existing account: current password only, server error shown", async () => {
    setSearch("token=inv");
    api.invitationInfo.mockResolvedValue(info(true));
    api.acceptInvite.mockRejectedValue(bad(400, "Current password is incorrect"));
    r(<AcceptInvite />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Your current password"), "whatever");
    expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Join organization" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect");
    expect(api.acceptInvite).toHaveBeenCalledWith({
      token: "inv",
      password: "whatever",
      full_name: null,
    });
  });
});
