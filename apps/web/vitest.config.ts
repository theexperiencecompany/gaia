import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
  test: {
    // Every co-located test under src/, not just src/__tests__ — narrow globs
    // silently drop any test placed next to its module (it never runs and
    // nothing tells you).
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    globals: true,
    environment: "node",
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
        // Allow vite to resolve internal bare specifiers inside ESM packages
        // that omit file extensions (e.g. @openuidev/react-lang/dist/index.js
        // imports from "./library" without ".js")
        inline: ["@openuidev/react-lang"],
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
      "@shared": path.resolve(__dirname, "../../libs/shared/ts/src"),
    },
    // Support extensionless imports inside ESM packages
    extensions: [".mjs", ".js", ".ts", ".jsx", ".tsx", ".json"],
  },
});
