// Shared mock for next/navigation. Use with:
//   vi.mock("next/navigation", () => import("@/test/next-navigation"));
import { vi } from "vitest";

export const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn(), back: vi.fn() };
export let searchParams = new URLSearchParams();
export let pathname = "/home";

export function setSearch(q: string) {
  searchParams = new URLSearchParams(q);
}
export function setPathname(p: string) {
  pathname = p;
}

export const useRouter = () => router;
export const useSearchParams = () => searchParams;
export const usePathname = () => pathname;
export const redirect = vi.fn();
