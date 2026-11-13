import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
  test: {
    // Per project: parallel nx test tasks sharing the root cache race to clear it (ENOTEMPTY).
    fsModuleCachePath: "node_modules/.vitest-cache",
    // Every co-located test under src/, not just src/__tests__ — narrow globs
    // silently drop any test placed next to its module (it never runs and
    // nothing tells you).
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    globals: true,
    environment: "node",
    // One box, eight neighbouring lanes: tests at tens of ms idle cross 5s
    // under load. 20s still fails a real hang.
    testTimeout: 20_000,
    setupFiles: ["./vitest.setup.ts"],
    reporters: ["verbose"],
    // NEXT_PUBLIC_API_BASE_URL: the api client validates it at module load.
    // NODE_ENV is pinned because nx's run-commands executor injects production,
    // which flips app code that skips animation/pacing under test.
    env: {
      NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
      NODE_ENV: "test",
    },
    server: {
      deps: {
        // ESM packages importing extensionless specifiers ("./library",
        // next-intl's "next/navigation") resolve only when vite inlines them
        inline: ["@openuidev/react-lang", "next-intl"],
      },
    },
  },
  resolve: {
    // Mirror the path aliases declared in tsconfig.json so component modules
    // (which import "@icons" / "@shared/*") resolve under vitest.
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@icons": path.resolve(
        __dirname,
        "node_modules/@theexperiencecompany/gaia-icons/dist/solid-rounded",
      ),
      "@shared-assets": path.resolve(__dirname, "../../libs/shared/assets"),
      "@shared": path.resolve(__dirname, "../../libs/shared/ts/src"),
    },
    // Support extensionless imports inside ESM packages
    extensions: [".mjs", ".js", ".ts", ".jsx", ".tsx", ".json"],
  },
});
