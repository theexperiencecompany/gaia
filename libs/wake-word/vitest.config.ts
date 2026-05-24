import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    testTimeout: 30_000,
    hookTimeout: 30_000,
    environment: "node",
    pool: "forks",
    globalSetup: ["./test/setup-models.ts"],
    server: {
      deps: {
        // onnxruntime-node ships a native .node binding — let vitest load it
        // directly without trying to transform.
        external: ["onnxruntime-node"],
      },
    },
  },
});
