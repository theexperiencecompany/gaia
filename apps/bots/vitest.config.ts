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
      "@gaia/shared": path.resolve(
        __dirname,
        "../../libs/shared/ts/src/index.ts",
      ),
    },
  },
});
