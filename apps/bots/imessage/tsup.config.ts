import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: "esm",
  target: "node20",
  outDir: "dist",
  clean: true,
  noExternal: [/.*/],
  banner: {
    js: `import{createRequire as __gaiaCreateRequire}from"module";const require=__gaiaCreateRequire(import.meta.url);`,
  },
});
