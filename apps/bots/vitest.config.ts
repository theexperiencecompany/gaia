import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["__tests__/**/*.test.ts"],
    globals: true,
    testTimeout: 15000,
    hookTimeout: 10000,
    fileParallelism: false,
    sequence: {
      concurrent: false,
    },
    reporters: ["verbose"],
    logHeapUsage: false,
    silent: false,
  },
  resolve: {
    alias: {
      // Longest prefix first: Vitest matches these in order, so a bare
      // "@gaia/shared" entry above would swallow the subpath and resolve it to
      // "src/index.ts/analytics".
      "@gaia/shared/analytics": path.resolve(
        __dirname,
        "../../libs/shared/ts/src/analytics/index.ts",
      ),
      "@gaia/shared": path.resolve(
        __dirname,
        "../../libs/shared/ts/src/index.ts",
      ),
    },
  },
});
