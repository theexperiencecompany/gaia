// One self-contained CommonJS file: the API image ships node and dist/validate.cjs, no node_modules.
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));

await build({
  entryPoints: [resolve(here, "src/cli.ts")],
  outfile: resolve(here, "dist/validate.cjs"),
  bundle: true,
  platform: "node",
  target: "node22",
  format: "cjs",
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
  loader: { ".css": "empty" },
  // the validator's sources live under apps/web; resolve their packages from this one when
  // apps/web has no node_modules (the API image's build stage installs only this package)
  nodePaths: [resolve(here, "node_modules")],
  logLevel: "warning",
});
