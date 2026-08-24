import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Root __tests__ plus every co-located test — narrow globs silently drop
    // any test placed next to its module.
    include: ["__tests__/**/*.test.ts", "src/**/*.test.ts"],
    globals: true,
    environment: "node",
    reporters: ["verbose"],
  },
});
