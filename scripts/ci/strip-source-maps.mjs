/**
 * Remove sourceMappingURL comments from the served static assets.
 *
 * The maps themselves are uploaded to Sentry and deleted; the comments left in
 * the JS/CSS are what squirrel's `perf/source-maps` rule reports. Only the
 * static asset tree is touched — server bundles and third-party code mention
 * the string legitimately.
 */
import fs from "node:fs";
import path from "node:path";

const root = process.argv[2] ?? "apps/web/.open-next/assets";
const EXTENSIONS = /\.(?:js|mjs|css)$/;
const LINE_COMMENT = /\/\/# sourceMappingURL=\S+/g;
const BLOCK_COMMENT = /\/\*# sourceMappingURL=[^*]*\*\//g;

let stripped = 0;
let scanned = 0;

function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      walk(file);
      continue;
    }
    if (!EXTENSIONS.test(entry.name)) continue;
    scanned += 1;
    const source = fs.readFileSync(file, "utf8");
    const cleaned = source.replace(LINE_COMMENT, "").replace(BLOCK_COMMENT, "");
    if (cleaned !== source) {
      fs.writeFileSync(file, cleaned);
      stripped += 1;
    }
  }
}

walk(root);

const remaining = [];
function findRemaining(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      findRemaining(file);
    } else if (EXTENSIONS.test(entry.name)) {
      if (fs.readFileSync(file, "utf8").includes("sourceMappingURL")) {
        remaining.push(file);
      }
    }
  }
}
findRemaining(root);

console.log(
  `sourceMappingURL: stripped ${stripped} of ${scanned} asset files (${remaining.length} remaining)`,
);
if (remaining.length > 0) {
  console.error(remaining.slice(0, 10).join("\n"));
  process.exit(1);
}
