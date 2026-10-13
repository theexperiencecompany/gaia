#!/usr/bin/env node
// CI gate: reports programmatic SEO pages whose metaDescription exceeds 155
// chars and exits 1 if any do. Check-only on purpose: a blind cut keeps the
// competitor half and drops the GAIA pitch, so a human rewrites each one.
//
// Usage: node scripts/seo/check-descriptions.mjs
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DATA_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../public/data");
const FEATURES = ["comparisons", "alternatives", "glossary", "personas"];
const LIMIT = 155;

const violations = [];
let scanned = 0;

for (const feature of FEATURES) {
  const dir = join(DATA_ROOT, feature);
  for (const file of readdirSync(dir)) {
    if (!file.endsWith(".json") || file.startsWith("_")) continue;
    const { metaDescription } = JSON.parse(readFileSync(join(dir, file), "utf8"));
    if (typeof metaDescription !== "string") continue;
    scanned++;
    const length = metaDescription.replace(/\s+/g, " ").trim().length;
    if (length > LIMIT) violations.push(`${feature}/${file}: ${length} chars`);
  }
}

console.log(`[check-descriptions] scanned ${scanned} pages, ${violations.length} over ${LIMIT} chars`);
for (const v of violations) console.log(`  - ${v}`);
process.exit(violations.length > 0 ? 1 : 0);
