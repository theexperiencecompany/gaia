import { defineConfig } from "tsup";

export default defineConfig({
  // deploy-commands ships in the image so a self-host install can register its own app's commands.
  entry: ["src/index.ts", "src/deploy-commands.ts"],
  format: "esm",
  target: "node20",
  outDir: "dist",
  clean: true,
  noExternal: [/.*/],
  banner: {
    js: `import{createRequire as __gaiaCreateRequire}from"module";const require=__gaiaCreateRequire(import.meta.url);`,
  },
});
