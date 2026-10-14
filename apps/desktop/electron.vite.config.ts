import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";

// @gaia/shared (a no-build workspace lib pointing at .ts source) is build-time-only,
// not a package.json dependency — a node_modules symlink resolves outside the app
// dir and breaks electron-builder's asar packager. Aliased to source instead.
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
