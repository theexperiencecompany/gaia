// One self-contained CommonJS file: the API image ships node and dist/validate.cjs, no node_modules.
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
// The bundle runs on the node that builds it: the repo's pin, here and in the API image.
const [nodeMajor] = process.versions.node.split(".");

await build({
  entryPoints: ["@gaia/artifacts/cli"],
  absWorkingDir: here,
  outfile: resolve(here, "dist/validate.cjs"),
  bundle: true,
  platform: "node",
  target: `node${nodeMajor}`,
  format: "cjs",
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
  loader: { ".css": "empty" },
  logLevel: "warning",
});
