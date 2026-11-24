import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { LAST_ORG_KEY } from "@/lib/org";
import { router, setSearch } from "@/test/next-navigation";

import { LoginForm, loginErrorMessage, postLoginUrl } from "./login-form";

vi.mock("next/navigation", () => import("@/test/next-navigation"));
const loginMock = vi.fn();
vi.mock("@/api/generated/endpoints/auth/auth", () => ({ login: (b: unknown) => loginMock(b) }));
const refreshMock = vi.fn();
vi.mock("@/lib/fetcher", () => ({ refreshOnce: () => refreshMock() }));

function renderForm() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <LoginForm />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  loginMock.mockReset();
  refreshMock.mockReset();
  router.replace.mockReset();
  setSearch("");
  vi.spyOn(console, "info").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

describe("placeholder login", () => {
  it("silent refresh success skips the form and goes to next (D6)", async () => {
    refreshMock.mockResolvedValue(true);
    setSearch("next=/users%3Fx%3D1");
    renderForm();
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/post-login?next=%2Fusers%3Fx%3D1"),
    );
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("logs in, clears a stale org and goes to /post-login", async () => {
    refreshMock.mockResolvedValue(false);
    localStorage.setItem(LAST_ORG_KEY, "other-org");
    loginMock.mockResolvedValue({ user: {}, memberships: [] });
    renderForm();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), " owner@acme.test ");
    await user.type(screen.getByLabelText("Password"), "secret-pass-1");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/post-login"));
    expect(loginMock).toHaveBeenCalledWith({ email: "owner@acme.test", password: "secret-pass-1" });
    expect(localStorage.getItem(LAST_ORG_KEY)).toBeNull();
  });

  it("ignores an unsafe next", async () => {
    refreshMock.mockResolvedValue(false);
    setSearch("next=https://evil.com");
    loginMock.mockResolvedValue({});
    renderForm();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/post-login"));
  });

  it("shows the generic message on 401 and stays on the page", async () => {
    refreshMock.mockResolvedValue(false);
    loginMock.mockRejectedValue(
      new ApiError({ status: 401, code: "unauthenticated", message: "Invalid email or password" }),
    );
    renderForm();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("validates before calling the API", async () => {
    refreshMock.mockResolvedValue(false);
    renderForm();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("has a forgot-password link", async () => {
    refreshMock.mockResolvedValue(false);
    renderForm();
    expect(await screen.findByRole("link", { name: "Forgot password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("postLoginUrl keeps only safe next values", () => {
    expect(postLoginUrl(null)).toBe("/post-login");
    expect(postLoginUrl("/users")).toBe("/post-login?next=%2Fusers");
    expect(postLoginUrl("//evil.com")).toBe("/post-login");
  });

  it("error messages", () => {
    const e = (status: number, extra = {}) =>
      new ApiError({ status, code: "x", message: "server says", ...extra });
    expect(loginErrorMessage(e(429, { retryAfter: 30 }))).toBe(
      "Too many attempts. Try again in 30 s.",
    );
    expect(loginErrorMessage(e(0))).toMatch(/Cannot reach/);
    expect(loginErrorMessage(e(403))).toBe("server says");
    expect(loginErrorMessage(new Error("boom"))).toMatch(/Something went wrong/);
  });
});
