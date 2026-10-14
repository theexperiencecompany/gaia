import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

// @gaia/shared is a no-build TS workspace lib the published @heygaia/cli does
// NOT depend on at runtime, so a bare `@gaia/shared/*` import would crash under
// --packages=external. Resolve it to source instead, mirroring apps/desktop's vite alias.
const __dirname = dirname(fileURLToPath(import.meta.url));
const SHARED_SRC = resolve(__dirname, "../../libs/shared/ts/src");

const sharedAliasPlugin = {
  name: "gaia-shared-alias",
  setup(pluginBuild) {
    pluginBuild.onResolve({ filter: /^@gaia\/shared(\/.*)?$/ }, (args) => {
      const sub = args.path.replace(/^@gaia\/shared\/?/, "");
      const base = sub ? resolve(SHARED_SRC, sub) : resolve(SHARED_SRC, "index");
      // Plugin-returned paths are final (no extension resolution), so mirror the
      // module resolver: prefer `<base>.ts`, fall back to `<base>/index.ts`.
      const candidates = [`${base}.ts`, resolve(base, "index.ts")];
      const target = candidates.find((candidate) => existsSync(candidate));
      if (!target) {
        throw new Error(`Cannot resolve @gaia/shared import: ${args.path}`);
      }
      return { path: target };
    });
  },
};

await build({
  entryPoints: ["src/index.ts"],
  bundle: true,
  platform: "node",
  target: "node18",
  format: "esm",
  packages: "external",
  outfile: "dist/index.js",
  minify: true,
  plugins: [sharedAliasPlugin],
});
