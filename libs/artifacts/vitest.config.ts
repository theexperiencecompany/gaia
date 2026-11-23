import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Per project: parallel nx test tasks sharing the root cache race to clear it (ENOTEMPTY).
    fsModuleCachePath: "node_modules/.vitest-cache",
    include: ["src/**/*.test.ts"],
    environment: "node",
    server: {
      deps: {
        // ESM packages importing extensionless specifiers resolve only when vite inlines them
        inline: ["@openuidev/react-lang", "@openuidev/react-ui"],
      },
    },
  },
});
