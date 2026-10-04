#!/usr/bin/env node
// CI gate: reports metaDescription strings over 155 chars in programmatic
// SEO entries. Check-only on purpose — trimming is an editorial decision
// (trailing sentences usually carry the GAIA pitch; blind cuts keep the
// competitor half and drop ours, plus naive rewrites break the object
// literal). A human rewrites each flagged entry.
//
// Usage: node scripts/seo/trim-descriptions.mjs [--check]
//   --check: report violations, exit 1 if any (default)
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(root, "../..");
const DIRS = [
  "src/features/comparisons/data/entries",
  "src/features/alternatives/data/entries",
  "src/features/glossary/data",
  "src/features/personas/data",
];
const LIMIT = 155;

function findEntryFiles() {
  const out = [];
  for (const d of DIRS) {
    const abs = path.join(webRoot, d);
    if (!fs.existsSync(abs)) continue;
    for (const f of fs.readdirSync(abs)) {
      if (f.endsWith(".ts") && !f.startsWith("index")) out.push(path.join(abs, f));
    }
  }
  return out;
}

// Match metaDescription: "..." including multi-line double-quoted strings.
// Files in this repo use double quotes for these fields (verified).
function extract(content) {
  const m = content.match(/metaDescription:\s*"([\s\S]*?)"(?=,\s*\n)/);
  return m ? { raw: m[0], text: m[1], index: m.index } : null;
}

function cleanTrim(text) {
  const one = text.replace(/\s+/g, " ").trim();
  if (one.length <= LIMIT) return { trimmed: one, cut: false };
  // accumulate whole sentences
  const parts = one.match(/[^.!?]+[.!?]+["']?|\S+$/g) || [one];
  let acc = "";
  for (const s of parts) {
    const next = acc ? `${acc} ${s.trim()}` : s.trim();
    if (next.length <= LIMIT) acc = next;
    else break;
  }
  if (acc && acc.length >= 100) return { trimmed: acc, cut: true };
  return { trimmed: one, cut: false, skip: true };
}

const mode = "check";
const files = findEntryFiles();
let trimmed = 0;
const skips = [];
const stillLong = [];

for (const f of files) {
  const content = fs.readFileSync(f, "utf8");
  const ex = extract(content);
  if (!ex) continue;
  const res = cleanTrim(ex.text);
  if (res.skip) {
    skips.push(`${path.basename(f)}: ${ex.text.replace(/\s+/g, " ").trim().length} chars, no sentence cut`);
    continue;
  }
  if (!res.cut && res.trimmed.length > LIMIT) {
    stillLong.push(f);
  }
}

console.log(`[trim-descriptions] scanned ${files.length} files, trimmed ${trimmed}`);
if (skips.length) {
  console.log(`[trim-descriptions] SKIPPED (needs human, ${skips.length}):`);
  for (const s of skips) console.log(`  - ${s}`);
}
if (mode === "check") {
  // count violations without writing
  let v = 0;
  for (const f of files) {
    const ex = extract(fs.readFileSync(f, "utf8"));
    if (ex && cleanTrim(ex.text).trimmed.length > LIMIT) v++;
  }
  console.log(`[trim-descriptions] --check: ${v} files over ${LIMIT} chars`);
  process.exit(v > 0 ? 1 : 0);
}
