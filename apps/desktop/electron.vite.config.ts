import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";

// @gaia/shared is a no-build TypeScript workspace lib — its package.json
// "exports" point straight at .ts source. electron-vite/rollup will not
// transpile a .ts file resolved from node_modules, so every @gaia/shared
// import is aliased to its source path and bundled as if it were app code
// (and excluded from externalization below for the same reason). The regex
// covers all subpaths — current and future — so no per-entry maintenance.
const SHARED_SRC = resolve(__dirname, "../../libs/shared/ts/src");
const sharedAlias = [
  { find: /^@gaia\/shared$/, replacement: resolve(SHARED_SRC, "index.ts") },
  { find: /^@gaia\/shared\/(.*)$/, replacement: `${SHARED_SRC}/$1` },
];

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin({ exclude: ["@gaia/shared"] })],
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
    plugins: [externalizeDepsPlugin({ exclude: ["@gaia/shared"] })],
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
