import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: "esm",
  target: "node20",
  outDir: "dist",
  clean: true,
  noExternal: [/.*/],
  banner: {
    js: `#!/usr/bin/env node\nimport{createRequire}from"module";const require=createRequire(import.meta.url);`,
  },
});
