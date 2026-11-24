import type { Metadata } from "next";
import type { ReactNode } from "react";

import { APP_NAME } from "@/config/site";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: "Multi-tenant SaaS scaffold",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning: next-themes sets the class on <html> before hydration.
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
