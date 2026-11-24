import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeMe, platformMe } from "@/test/fixtures";
import { router, setSearch } from "@/test/next-navigation";
import { renderWithSession } from "@/test/render";

import PostLoginPage from "./page";

vi.mock("next/navigation", () => import("@/test/next-navigation"));

beforeEach(() => {
  router.replace.mockReset();
  setSearch("");
  vi.spyOn(console, "info").mockImplementation(() => {});
});

describe("/post-login", () => {
  it("sends each user to their landing path", async () => {
    await act(async () => void renderWithSession(<PostLoginPage />, makeMe()));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/home/owner"));
  });

  it("platform admin -> /platform", async () => {
    await act(async () => void renderWithSession(<PostLoginPage />, platformMe()));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/platform"));
  });

  it("no organization -> /no-organization", async () => {
    await act(
      async () =>
        void renderWithSession(<PostLoginPage />, makeMe({ org: null, landing_path: null })),
    );
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/no-organization"));
  });

  it("honours a safe deep link", async () => {
    setSearch("next=/users");
    await act(async () => void renderWithSession(<PostLoginPage />, makeMe()));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/users"));
  });
});
