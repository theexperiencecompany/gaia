import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Per project: parallel nx test tasks sharing the root cache race to clear it (ENOTEMPTY).
    fsModuleCachePath: "node_modules/.vitest-cache",
    include: ["src/**/*.test.ts"],
    globals: true,
    testTimeout: 10000,
  },
  resolve: {
    alias: {
      "@/": `${path.resolve(__dirname, "src")}/`,
      "@icons": path.resolve(__dirname, "src/lib/gaia-icons.tsx"),
    },
  },
});
