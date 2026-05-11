import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts", "src/styles.css"],
  format: ["esm"],
  dts: true,
  clean: true,
  sourcemap: true,
  // Resolve via tsconfig paths (esbuild reads tsconfig.json paths automatically).
  tsconfig: "./tsconfig.json",
  // External: keep React + heavy peer deps unbundled so consumers dedupe.
  // Externalize npm packages while bundling path-aliased and relative imports.
  // Negative lookahead excludes @/..., @shared/..., ./, ../, /  — these resolve
  // via tsconfig paths or relative paths and must be inlined into the bundle.
  // Everything else is treated as a peer/runtime npm dep.
  external: [/^(?!@\/|@shared\/|\.\.?\/|\/)/],
  loader: {
    ".css": "copy",
  },
  injectStyle: false,
  treeshake: true,
});
