import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
  test: {
    include: ["src/__tests__/**/*.test.ts", "src/__tests__/**/*.test.tsx"],
    globals: true,
    environment: "node",
    reporters: ["verbose"],
    // Component modules transitively import the api client, which validates
    // this at module load. The contract tests make no real requests.
    env: {
      NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
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
        "../../node_modules/@theexperiencecompany/gaia-icons/dist/solid-rounded",
      ),
      "@shared": path.resolve(__dirname, "../../libs/shared/ts/src"),
    },
    // Support extensionless imports inside ESM packages
    extensions: [".mjs", ".js", ".ts", ".jsx", ".tsx", ".json"],
  },
});
