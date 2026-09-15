import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts", "src/cli.ts"],
  format: "esm",
  target: "node20",
  outDir: "dist",
  clean: true,
  noExternal: [/.*/],
  // Shebang first so dist/cli.js is directly executable as the gaia-sim bin; the
  // createRequire shim lets bundled CJS deps (axios, amqplib) call require() from
  // an ESM bundle. Node strips the shebang on library import, so it's harmless here.
  banner: {
    js: `#!/usr/bin/env node\nimport{createRequire}from"module";const require=createRequire(import.meta.url);`,
  },
});
