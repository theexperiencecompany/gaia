import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Per project: parallel nx test tasks sharing the root cache race to clear it (ENOTEMPTY).
    fsModuleCachePath: "node_modules/.vitest-cache",
    include: ["__tests__/**/*.test.ts"],
    globals: true,
    testTimeout: 10000,
    // Ink draws only the last frame when it detects CI; the UI tests drive a fake TTY.
    env: { CI: "false", CONTINUOUS_INTEGRATION: "false" },
  },
});
