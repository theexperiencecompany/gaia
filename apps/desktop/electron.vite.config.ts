import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";

// Mirrors the tsconfig.json "paths" entry — @gaia/shared is a TS-source
// workspace lib, so it must be bundled from source rather than resolved
// (and externalized) through node_modules hoisting.
const sharedAlias = {
  "@gaia/shared/desktop-tools": resolve(
    __dirname,
    "../../libs/shared/ts/src/desktop-tools/index.ts",
  ),
};

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: sharedAlias,
    },
    build: {
      lib: {
        entry: resolve(__dirname, "src/main/index.ts"),
        formats: ["es"],
      },
      rollupOptions: {
        output: {
          entryFileNames: "[name].mjs",
        },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: sharedAlias,
    },
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, "src/preload/index.ts"),
        },
      },
    },
  },
});
