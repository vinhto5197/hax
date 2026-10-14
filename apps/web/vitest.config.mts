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
    // A spy or a stubbed global never outlives the test that made it.
    restoreMocks: true,
    unstubGlobals: true,
  },
});
