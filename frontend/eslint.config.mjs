// ESLint flat config: Next.js core-web-vitals + TypeScript rules, Prettier
// owns formatting. Generated API code is not linted (do not edit it).
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import prettier from "eslint-config-prettier/flat";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  prettier,
  globalIgnores([
    ".next/**",
    "node_modules/**",
    ".pnpm-store/**",
    "coverage/**",
    "src/api/generated/**",
    "src/api/.gen-check/**",
    "next-env.d.ts",
    // Own package (Playwright), checked in its own container (B12 D8).
    "tests/e2e/**",
  ]),
]);
