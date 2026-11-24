import type { NextConfig } from "next";

// B08 D17: the browser only ever talks to Next.js (same origin, no CORS).
// /api/<path> is proxied to FastAPI, which serves the path WITHOUT the /api
// prefix (api_spec.md header). The refresh cookie is scoped to Path=/api/auth,
// which only matches because of this rewrite.
//
// BACKEND_INTERNAL_URL is the container-network address (docker-compose.yml);
// the fallback serves `pnpm dev` run directly on the host.
const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8200";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // To open the dev server from another machine set PUBLIC_HOST in .env (B13
  // D4; compose passes it as ALLOWED_DEV_ORIGINS). Next 16 blocks cross-origin dev resources unless the origin is listed.
  allowedDevOrigins: (process.env.ALLOWED_DEV_ORIGINS ?? "localhost")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
  // B09 D13: pages are never cached by the browser, so Back after logout
  // cannot show a stored copy. /api responses carry the backend's headers.
  async headers() {
    return [
      {
        source: "/((?!api/|_next/static|_next/image).*)",
        headers: [{ key: "Cache-Control", value: "no-store" }],
      },
    ];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
