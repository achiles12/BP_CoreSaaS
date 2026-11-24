"use client";
// Last-resort boundary (S16): replaces the root layout when it crashes, so it
// renders its own <html>/<body> and uses no providers or Tailwind tokens.
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[fe] ui.global_error", { message: error.message, digest: error.digest });
  }, [error]);
  return (
    <html lang="en">
      <body
        style={{ fontFamily: "system-ui, sans-serif", textAlign: "center", padding: "4rem 1rem" }}
      >
        <h1>Something went wrong</h1>
        <p>The application failed to load{error.digest ? ` (ref ${error.digest})` : ""}.</p>
        <button type="button" onClick={reset} style={{ padding: "0.5rem 1rem" }}>
          Try again
        </button>
      </body>
    </html>
  );
}
