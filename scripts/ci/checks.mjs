#!/usr/bin/env node
/**
 * checks.mjs — the static hygiene gates over the TypeScript/JS surface.
 *
 * Subcommands:
 *   biome               Biome over CHANGED_FILES (or the repo), failing on any
 *                       error and on a dead biome-ignore (`suppressions/unused`,
 *                       a warning biome itself never fails on). CI and
 *                       `mise ci:local` both run this.
 *   file-sizes [--enforce-all] [--quiet]
 *                       File size gate. Default mode reports every file over
 *                       its target limit but only FAILS on the 1200-line hard
 *                       cap, so existing monsters surface while anything new
 *                       is blocked. --enforce-all fails on any file over its
 *                       limit; --quiet suppresses the report.
 *   components-per-file Fail when a .tsx file exports more than 2 React
 *                       components.
 *   types-location [--enforce|--strict]
 *                       Fail (or, without the flag, report) when a non-type
 *                       file exports more than 3 types.
 *   duplication         Fail when more than 3% of the lines this branch ADDS
 *                       sit inside a copy-pasted block (the SonarCloud
 *                       denominator, reproduced with jscpd).
 *   evlog-map-bots [--json] [--min-score N] [--min-entries N] [--files-from F]
 *                       Observability score for the bots' wide-event entry
 *                       points. Implementation in lib/evlog-map-bots.mjs.
 *   api-schema [--write]
 *                       Regenerate apps/api/openapi.json and the TypeScript
 *                       types in libs/shared/ts/src/api/generated, then fail
 *                       if either differs from what is committed. --write
 *                       regenerates without checking (what `mise api:types`
 *                       runs).
 *   analytics-catalog [--write]
 *                       Regenerate analytics-catalog.json and the TypeScript
 *                       event types in libs/shared/ts/src/analytics/generated
 *                       from the Pydantic catalog, then fail if either differs
 *                       from what is committed. --write is `mise analytics:types`.
 *   cli-config-schema [--write]
 *                       Regenerate the CLI's vendored config schema
 *                       (packages/cli/src/lib/api-config-schema.generated.json)
 *                       from the API's settings groups and capability table,
 *                       then fail if it differs from what is committed.
 *                       --write is `mise cli:schema`.
 *   deploy-templates [--write]
 *                       Regenerate deploy/coolify/gaia.yaml, render.yaml and
 *                       deploy/proxy.Dockerfile from the self-host compose
 *                       file, its Caddyfile and the CLI's machine secrets
 *                       (lib/deploy_templates.py), then fail if any differs
 *                       from what is committed. --write is `mise deploy:templates`.
 *   doc-comments        Fail on a JSDoc block that narrates (>6 lines) or
 *                       restates its declaration/@param, a run of more than
 *                       3 // lines, or a banner inside a body. The TS half of
 *                       tools/lints/docstring_slop.py + comment_slop.py;
 *                       implementation in lib/doc-comments.mjs.
 *   api-schema-types    Four rules over every .ts/.tsx outside the generated
 *                       dir, each failing on the hand-written twin of a
 *                       Pydantic model: a declaration NAMED after a component
 *                       schema; any declaration at all inside an API-type
 *                       directory (API_TYPE_DIRS) that is not a re-export or
 *                       an alias of a generated name; a declaration whose
 *                       FIELDS are a component schema's fields under another
 *                       name; and an untyped `apiService` call in web feature
 *                       code. The last two ratchet against the baselines in
 *                       scripts/ci/baselines.
 *   heroui-style-overrides
 *                       Fail when a className or style prop on a component
 *                       imported from "@heroui/react" sets colour, background,
 *                       border colour, radius or padding outside the files
 *                       that own HeroUI's look, inline or through a constant,
 *                       ratcheted against a baseline.
 *   heroui-usage        Fail on a v2 HeroUI API, a Switch/Checkbox without its
 *                       parts, or a bare HeroUI component a GAIA wrapper
 *                       replaces. Both rules live in lib/heroui-usage.mjs.
 *   api-client-imports  Fail when a file outside apps/mobile/src/lib imports
 *                       the raw mobile API client, ratcheted against a
 *                       baseline. The web half of that boundary is Biome's
 *                       style/noRestrictedImports, scoped by an override.
 *   bot-handles         Every WhatsApp / Telegram / Discord link matches
 *                       libs/shared/bot-identity.json. Runs without
 *                       node_modules (lib/bot-handles.mjs).
 *
 * Every other subcommand lives in lib/checks-commands.mjs and needs
 * node_modules; without it this exits 1 naming the install command.
 *
 * Env contract: CHANGED_FILES (see lib/explicit-file-list.mjs) scopes the
 * file-walking gates to a lane's changed files; empty means full scan.
 * `duplication` reads GAIA_PR_BASE, then GITHUB_BASE_REF, for its diff base
 * (default master).
 */
import { existsSync } from "node:fs";
import { runBotHandles } from "./lib/bot-handles.mjs";

// bot-handles is an always-run commit hook that reads only the tree, so a
// fresh worktree runs it before anyone has installed node_modules.
const WITHOUT_NODE_MODULES = { "bot-handles": runBotHandles };
// pnpm records a finished install here.
const PNPM_INSTALL_MARKER = new URL(
  "../../node_modules/.modules.yaml",
  import.meta.url,
);

const sub = process.argv[2];
if (Object.hasOwn(WITHOUT_NODE_MODULES, sub ?? "")) {
  WITHOUT_NODE_MODULES[sub]();
} else if (!existsSync(PNPM_INSTALL_MARKER)) {
  console.error(
    `❌ checks.mjs${sub ? ` ${sub}` : ""}: node_modules is not installed in this checkout. ` +
      "Run: pnpm install --frozen-lockfile",
  );
  process.exit(1);
} else {
  const { main } = await import("./lib/checks-commands.mjs");
  main();
}
