import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["__tests__/**/*.test.ts"],
    globals: true,
    testTimeout: 10000,
    // Ink draws only the last frame when it detects CI; the UI tests drive a fake TTY.
    env: { CI: "false", CONTINUOUS_INTEGRATION: "false" },
  },
});
