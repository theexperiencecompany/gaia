import { defineConfig } from "tsup";

export default defineConfig({
  // set-commands ships in the image so a self-host install can set its own bot's command menu.
  entry: ["src/index.ts", "src/set-commands.ts"],
  format: "esm",
  target: "node20",
  outDir: "dist",
  clean: true,
  noExternal: [/.*/],
  banner: {
    js: `import{createRequire as __gaiaCreateRequire}from"module";const require=__gaiaCreateRequire(import.meta.url);`,
  },
});
