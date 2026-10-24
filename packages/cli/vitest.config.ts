import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Per project: parallel nx test tasks sharing the root cache race to clear it (ENOTEMPTY).
    fsModuleCachePath: "node_modules/.vitest-cache",
    include: ["__tests__/**/*.test.ts"],
    globals: true,
    testTimeout: 10000,
  },
});
