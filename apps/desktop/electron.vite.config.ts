import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";

// @gaia/shared is a no-build TypeScript workspace lib — its package.json
// "exports" point straight at .ts source. It is a BUILD-TIME source dependency
// inlined into the bundle, not a runtime node_modules module, so it is NOT a
// package.json dependency: a workspace symlink under node_modules is unused at
// runtime and breaks electron-builder's asar packager (it resolves outside the
// app dir). Instead, every @gaia/shared import is aliased to its source path
// and bundled as app code. The regex covers all subpaths — current and future
// — so there is no per-entry maintenance.
const SHARED_SRC = resolve(__dirname, "../../libs/shared/ts/src");
const sharedAlias = [
  { find: /^@gaia\/shared$/, replacement: resolve(SHARED_SRC, "index.ts") },
  { find: /^@gaia\/shared\/(.*)$/, replacement: `${SHARED_SRC}/$1` },
];

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
