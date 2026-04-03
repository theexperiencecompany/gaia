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
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
    // Support extensionless imports inside ESM packages
    extensions: [".mjs", ".js", ".ts", ".jsx", ".tsx", ".json"],
  },
});
