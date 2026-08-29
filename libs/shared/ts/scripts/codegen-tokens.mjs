#!/usr/bin/env node
/**
 * Codegen: libs/shared/ts/src/design/tokens.generated.ts
 * Source: apps/web/src/app/styles/globals.css + config/design.tokens.json
 * Usage: node libs/shared/ts/scripts/codegen-tokens.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../../..");
const cssPath = resolve(root, "apps/web/src/app/styles/globals.css");
const dtcgPath = resolve(root, "config/design.tokens.json");
const outPath = resolve(root, "libs/shared/ts/src/design/tokens.generated.ts");

const css = readFileSync(cssPath, "utf8");
const dtcg = JSON.parse(readFileSync(dtcgPath, "utf8"));

console.log(`Reading ${cssPath} (${css.length} bytes)`);
// Simple validation: ensure key vars exist
const required = ["--color-primary", "--color-primary-bg", "--radius"];
for (const v of required) {
  if (!css.includes(v)) console.warn(`WARN missing ${v} in globals.css`);
}
console.log(`DTCG tokens: ${Object.keys(dtcg).join(", ")}`);
console.log(`Output would be ${outPath}`);
console.log("NOTE: actual file is hand-maintained but this script validates sources");
// Optionally regenerate? For now just validate.
