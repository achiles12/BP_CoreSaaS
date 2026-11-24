import { defineConfig } from "orval";

// B08 D15: typed TanStack Query hooks generated from the backend schema.
// The schema snapshot (openapi.json) is produced offline by
// `python -m app.openapi_dump` via `make gen-client`; never edit the output.
// ORVAL_INPUT/ORVAL_OUTPUT let `make gen-client-check` generate from a fresh
// schema into src/api/.gen-check (same depth, so relative imports match).
const input = process.env.ORVAL_INPUT ?? "./openapi.json";
const target = process.env.ORVAL_OUTPUT ?? "./src/api/generated";

export default defineConfig({
  api: {
    input: { target: input },
    output: {
      mode: "tags-split",
      target: `${target}/endpoints`,
      schemas: `${target}/model`,
      client: "react-query",
      httpClient: "fetch",
      clean: true,
      formatter: "prettier",
      override: {
        mutator: { path: "./src/lib/fetcher.ts", name: "customFetch" },
        // The mutator returns the parsed body itself (or throws ApiError),
        // not orval's {data, status, headers} wrapper.
        fetch: { includeHttpResponseReturnType: false },
        // Defaults: GET -> useQuery, other methods -> useMutation.
        query: { signal: true },
      },
    },
  },
});
