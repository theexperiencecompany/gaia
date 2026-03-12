import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [],
    poolOptions: {
      forks: {
        execArgv: ["--max-old-space-size=8192"],
      },
      threads: {
        execArgv: ["--max-old-space-size=8192"],
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@icons": path.resolve(__dirname, "./src/components/ui/icons"),
    },
  },
});
