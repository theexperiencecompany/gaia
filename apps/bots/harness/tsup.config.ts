import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts", "src/cli.ts"],
  format: "esm",
  target: "node20",
  outDir: "dist",
  clean: true,
  noExternal: [/.*/],
  // Shebang first so `dist/cli.js` is directly executable as the `gaia-sim`
  // bin; the createRequire shim after it lets bundled CJS deps (axios, amqplib)
  // call require() from an ESM bundle. Node strips the shebang when index.js is
  // imported as a library, so applying the banner to both entries is harmless.
  banner: {
    js: `#!/usr/bin/env node\nimport{createRequire}from"module";const require=createRequire(import.meta.url);`,
  },
});
