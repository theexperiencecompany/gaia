// The regenerate-and-diff gates over committed generated files: each one
// rebuilds its artifacts from their source of truth, then fails when the tree
// differs from what is committed, which catches a missed `mise <task>`.
// `--write` regenerates without the diff, and is what each mise task runs.
// Reached through `checks.mjs api-schema | analytics-catalog |
// cli-config-schema | deploy-templates`; never run directly.
import { execFileSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

export const OPENAPI_JSON = "apps/api/openapi.json";
const GENERATED_TYPES = "libs/shared/ts/src/api/generated/schema.d.ts";
const ANALYTICS_GENERATED_DIR = "libs/shared/ts/src/analytics/generated";
const ANALYTICS_CATALOG_JSON = `${ANALYTICS_GENERATED_DIR}/analytics-catalog.json`;
const CLI_CONFIG_SCHEMA = "packages/cli/src/lib/api-config-schema.generated.json";
const DEPLOY_TEMPLATES = [
  "deploy/coolify/gaia.yaml",
  "render.yaml",
  "deploy/proxy.Dockerfile",
];

const QUIET_ENV = { ...process.env, LOG_LEVEL: "ERROR" };

/** Exit 1 when any of paths differs from the committed tree; --write skips the diff. */
function failOnDrift(argv, paths, { drift, ok }) {
  if (argv.includes("--write")) return;
  const dirty = execFileSync("git", ["status", "--porcelain", "--", ...paths], {
    encoding: "utf8",
  }).trim();
  if (dirty) {
    console.log(dirty);
    console.error(`❌ ${drift}`);
    process.exit(1);
  }
  console.log(`✅ ${ok}`);
}

function regenerateApiSchema() {
  const opts = { stdio: "inherit" };
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "--project",
      "apps/api",
      "--group",
      "backend",
      "--group",
      "dev",
      "python",
      "apps/api/scripts/export_openapi.py",
    ],
    { ...opts, env: QUIET_ENV },
  );
  // tools/api-codegen is outside the workspace: it needs the JS compiler API
  // (ts.createPrinter), which the native 7.x package does not ship.
  const codegenDir = resolve("tools/api-codegen");
  const codegenBin =
    process.env.GAIA_OPENAPI_TS || join(codegenDir, "node_modules", ".bin", "openapi-typescript");
  if (!existsSync(codegenBin)) {
    // Never pass on the committed schema when regeneration was skipped.
    throw new Error(
      `${codegenBin} is missing. Run: pnpm --dir tools/api-codegen install --frozen-lockfile --ignore-workspace`,
    );
  }
  execFileSync(
    codegenBin,
    [
      resolve(OPENAPI_JSON),
      "--alphabetize",
      // A field with a default is optional on the wire for a request body; a
      // response-only model marks it required itself (ResponseModel).
      "--default-non-nullable=false",
      // One exported alias per component schema, under the API's own name
      // (`TodoResponse`, not `Schema<"TodoResponse">`): navigable, greppable,
      // and identical to the Pydantic class it came from.
      "--root-types",
      "--root-types-no-schema-prefix",
      "--root-types-keep-casing",
      "--output",
      resolve(GENERATED_TYPES),
    ],
    opts,
  );
}

export function cmdApiSchema(argv) {
  regenerateApiSchema();
  failOnDrift(argv, [OPENAPI_JSON, GENERATED_TYPES], {
    drift: "API schema drifted — run `mise api:types` and commit",
    ok: "openapi.json and the generated API types match the routes.",
  });
}

export function cmdAnalyticsCatalog(argv) {
  const opts = { stdio: "inherit" };
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "--project",
      "apps/api",
      "python",
      "-m",
      "shared.py.analytics.codegen",
    ],
    { ...opts, env: QUIET_ENV },
  );
  execFileSync(
    "pnpm",
    ["exec", "biome", "format", "--write", ANALYTICS_CATALOG_JSON],
    opts,
  );
  failOnDrift(argv, [ANALYTICS_GENERATED_DIR], {
    drift: "Analytics catalog drifted — run `mise analytics:types` and commit",
    ok: "The generated analytics event types match the catalog.",
  });
}

export function cmdCliConfigSchema(argv) {
  const schema = execFileSync(
    "uv",
    ["run", "--frozen", "python", "-m", "scripts.dump_config_schema"],
    { cwd: "apps/api", encoding: "utf8", env: QUIET_ENV },
  );
  writeFileSync(CLI_CONFIG_SCHEMA, schema);
  failOnDrift(argv, [CLI_CONFIG_SCHEMA], {
    drift:
      "The CLI config schema drifted from the API settings — run `mise cli:schema` and commit",
    ok: "The CLI config schema matches the API settings.",
  });
}

export function cmdDeployTemplates(argv) {
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "--project",
      "apps/api",
      "python",
      "scripts/ci/lib/deploy_templates.py",
    ],
    { stdio: "inherit" },
  );
  failOnDrift(argv, DEPLOY_TEMPLATES, {
    drift:
      "The deploy templates drifted from the self-host compose file — run `mise deploy:templates` and commit",
    ok: "The deploy templates match the self-host compose file.",
  });
}
