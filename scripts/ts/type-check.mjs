#!/usr/bin/env node
// Type-check (or emit) one project with tsrs, the Rust port of TypeScript.
//
//   node scripts/ts/type-check.mjs --noEmit
//   GAIA_TS_CHECKER=tsc node scripts/ts/type-check.mjs --noEmit
//
// tsrs is the default so there is one compiler in the repo. GAIA_TS_CHECKER=tsc
// runs the stock compiler through the same tsconfig, flags and cwd, which is
// what makes the two comparable when tsrs needs to be ruled out of a failure.
//
// Optional:
//   GAIA_TS_CHECKERS=N   tsrs only: --checkers N
//   GAIA_TS_VERBOSE=1    print the resolved binary to stderr
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const workspaceRoot = process.env.NX_WORKSPACE_ROOT || join(here, "..", "..");
const useTsrs = process.env.GAIA_TS_CHECKER !== "tsc";

const firstExisting = (candidates) => candidates.find((p) => existsSync(p));
const local = join(process.cwd(), "node_modules", ".bin");

const tsrsBinary = firstExisting([join(workspaceRoot, "node_modules", ".bin", "tsrs")]);
if (useTsrs && !tsrsBinary) {
  // Falling back to tsc here would make the CI shadow lane pass without ever
  // running the compiler it exists to judge.
  console.error("[type-check] GAIA_TS_CHECKER=tsrs but no tsrs binary was found at " +
    join(workspaceRoot, "node_modules", ".bin", "tsrs") + " — run pnpm install.");
  process.exit(1);
}

const binary = useTsrs
  ? tsrsBinary
  : firstExisting([join(local, "tsc"), join(workspaceRoot, "node_modules", ".bin", "tsc")]) || "tsc";

const args = process.argv.slice(2);
if (useTsrs && process.env.GAIA_TS_CHECKERS) {
  args.push("--checkers", process.env.GAIA_TS_CHECKERS);
}

if (process.env.GAIA_TS_VERBOSE) {
  console.error(`[type-check] ${useTsrs ? "tsrs" : "tsc"} ${args.join(" ")} (cwd=${process.cwd()})`);
}

const result = spawnSync(binary, args, { stdio: "inherit", env: process.env });

if (result.error) {
  console.error(`[type-check] failed to start ${binary}: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
