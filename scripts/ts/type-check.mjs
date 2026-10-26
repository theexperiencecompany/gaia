#!/usr/bin/env node
// Type-check (or emit) one project with tsrs, the Rust port of TypeScript.
//
//   node scripts/ts/type-check.mjs --noEmit
//   GAIA_TS_CHECKER=tsc node scripts/ts/type-check.mjs --noEmit
//
// tsrs is the default so there is one compiler in the repo. GAIA_TS_CHECKER=tsc
// runs the stock compiler through the same tsconfig, flags and cwd, which is
// what makes the two comparable when tsrs needs to be ruled out of a failure.
// On a platform tsrs publishes no binary for (Windows, Intel macOS) tsc runs
// instead: there is no tsrs to judge there.
//
// Optional:
//   GAIA_TS_CHECKERS=N   tsrs only: --checkers N
//   GAIA_TS_VERBOSE=1    print the resolved compiler to stderr
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const workspaceRoot = process.env.NX_WORKSPACE_ROOT || join(here, "..", "..");

// A compiler's entry is its package's own bin script, run on this node: the
// node_modules/.bin shims are shell scripts Windows cannot spawn.
function compilerEntry(fromDir, pkgName, binName) {
  const require = createRequire(join(fromDir, "package.json"));
  const manifestPath = require.resolve(`${pkgName}/package.json`);
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  return { manifest, entry: join(dirname(manifestPath), manifest.bin[binName]) };
}

function resolveTsrs() {
  try {
    return compilerEntry(workspaceRoot, "tsrs", "tsrs");
  } catch {
    // Falling back to tsc here would make the CI shadow lane pass without ever
    // running the compiler it exists to judge.
    console.error(`[type-check] tsrs is not installed under ${workspaceRoot} — run pnpm install.`);
    process.exit(1);
  }
}

// tsrs ships one optional native package per platform, @tsrs/<os>-<cpu>[-gnu|-musl].
function tsrsSupportsThisPlatform(manifest) {
  const prefix = `@tsrs/${process.platform}-${process.arch}`;
  return Object.keys(manifest.optionalDependencies ?? {}).some(
    (name) => name === prefix || name.startsWith(`${prefix}-`),
  );
}

const tsrs = process.env.GAIA_TS_CHECKER === "tsc" ? null : resolveTsrs();
const useTsrs = tsrs !== null && tsrsSupportsThisPlatform(tsrs.manifest);
const compiler = useTsrs ? tsrs : compilerEntry(process.cwd(), "typescript", "tsc");

const args = process.argv.slice(2);
if (useTsrs && process.env.GAIA_TS_CHECKERS) {
  args.push("--checkers", process.env.GAIA_TS_CHECKERS);
}

if (process.env.GAIA_TS_VERBOSE) {
  console.error(`[type-check] ${useTsrs ? "tsrs" : "tsc"} ${args.join(" ")} (cwd=${process.cwd()})`);
}

const result = spawnSync(process.execPath, [compiler.entry, ...args], {
  stdio: "inherit",
  env: process.env,
});

if (result.error) {
  console.error(`[type-check] failed to start ${compiler.entry}: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
