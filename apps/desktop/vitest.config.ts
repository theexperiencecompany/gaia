import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Per project: parallel nx test tasks sharing the root cache race to clear it (ENOTEMPTY).
    fsModuleCachePath: "node_modules/.vitest-cache",
    // Root __tests__ plus every co-located test — narrow globs silently drop
    // any test placed next to its module.
    include: ["__tests__/**/*.test.ts", "src/**/*.test.ts"],
    globals: true,
    environment: "node",
    reporters: ["verbose"],
  },
});
