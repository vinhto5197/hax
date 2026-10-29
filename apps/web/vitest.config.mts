import { fileURLToPath } from "node:url";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    // Mirrors `paths` in tsconfig.json; the two must change together.
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    include: ["**/*.test.{ts,tsx}"],
    exclude: [...configDefaults.exclude, ".next/**"],
    setupFiles: ["./vitest.setup.ts"],
    // The dev shell exports the root .env (direnv); tests must not see its API
    // origin, so URLs are the same-origin ones production uses.
    env: { NEXT_PUBLIC_API_URL: "" },
    // No spy, queued mock value or stubbed global outlives the test that made
    // it (restoreMocks alone keeps a module mock's unconsumed *Once values).
    restoreMocks: true,
    mockReset: true,
    unstubGlobals: true,
    // `make coverage` only. Pages and display components are exercised by
    // the Playwright journeys, which this report does not measure.
    coverage: {
      provider: "v8",
      include: ["app/**", "components/**", "hooks/**", "lib/**"],
      exclude: ["**/*.test.*", "lib/openapi.ts"],
      reporter: ["text-summary", "text"],
    },
  },
});
