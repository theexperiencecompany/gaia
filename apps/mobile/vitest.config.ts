import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
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
