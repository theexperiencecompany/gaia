#!/usr/bin/env node
/**
 * Copy-paste gate that matches what SonarCloud actually measures.
 *
 * jscpd's own threshold is a percentage over the WHOLE repo, so it is ~0.8% and
 * never trips for a single PR — a green run there tells you nothing about the
 * SonarCloud duplication gate. SonarCloud instead gates on duplicated lines
 * among the lines a PR CHANGES (the diff vs the base branch).
 *
 * This reproduces that denominator: it runs jscpd, then maps every detected
 * clone's line ranges onto the lines this branch adds vs the base, and fails
 * when that ratio exceeds the limit.
 *
 * It is an estimate (jscpd's tokenizer differs from SonarCloud's), but it is the
 * only local/CI signal correlated with the gate. SonarCloud stays authoritative.
 *
 * Base branch is taken from GITHUB_BASE_REF (set automatically on GitHub Actions
 * pull requests); locally it defaults to develop.
 */
import { execSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.GITHUB_BASE_REF
  ? `origin/${process.env.GITHUB_BASE_REF}`
  : "origin/develop";
const THRESHOLD = 3;

const sh = (cmd) =>
  execSync(cmd, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });

const repoRoot = sh("git rev-parse --show-toplevel").trim();
const rel = (p) =>
  p.startsWith(`${repoRoot}/`) ? p.slice(repoRoot.length + 1) : p;

let base;
try {
  base = sh(`git merge-base ${BASE} HEAD`).trim();
} catch {
  // Shallow clone or no common ancestor: fall back to the base ref tip.
  try {
    base = sh(`git rev-parse --verify ${BASE}^{commit}`).trim();
  } catch {
    console.error(
      `check-duplication: could not resolve base "${BASE}". ` +
        "Fetch it first (git fetch origin <branch>).",
    );
    process.exit(2);
  }
}

// Lines added on the new side, per file (working tree vs base, so uncommitted
// changes count too — this is meant to run before you push).
const added = new Map();
let currentFile = null;
for (const line of sh(`git diff --unified=0 ${base}`).split("\n")) {
  if (line.startsWith("+++ ")) {
    const p = line.slice(4).trim();
    currentFile = p === "/dev/null" ? null : p.replace(/^b\//, "");
  } else if (line.startsWith("@@") && currentFile) {
    const m = /\+(\d+)(?:,(\d+))?/.exec(line);
    if (m) {
      const start = Number(m[1]);
      const count = m[2] === undefined ? 1 : Number(m[2]);
      let set = added.get(currentFile);
      if (!set) added.set(currentFile, (set = new Set()));
      for (let i = 0; i < count; i++) set.add(start + i);
    }
  }
}

// Run jscpd (reuses .jscpd.json) and load the JSON report.
const outDir = mkdtempSync(join(tmpdir(), "jscpd-"));
sh(`pnpm exec jscpd --reporters json --output ${outDir} --silent .`);
const report = JSON.parse(
  readFileSync(join(outDir, "jscpd-report.json"), "utf8"),
);

// Files jscpd analyzed — defines the denominator scope, like SonarCloud.
const analyzed = new Set();
for (const fmt of Object.values(report.statistics?.formats ?? {})) {
  for (const f of Object.keys(fmt.sources ?? {})) analyzed.add(rel(f));
}

// Lines covered by at least one clone, per file.
const covered = new Map();
const cover = (f, s, e) => {
  let set = covered.get(f);
  if (!set) covered.set(f, (set = new Set()));
  for (let i = s; i <= e; i++) set.add(i);
};
for (const d of report.duplicates ?? []) {
  cover(rel(d.firstFile.name), d.firstFile.start, d.firstFile.end);
  cover(rel(d.secondFile.name), d.secondFile.start, d.secondFile.end);
}

// Changed lines that fall inside a duplicated block, in analyzed files only.
let changedLines = 0;
let dupChangedLines = 0;
const offenders = [];
for (const [file, addedSet] of added) {
  if (!analyzed.has(file)) continue;
  changedLines += addedSet.size;
  const cov = covered.get(file);
  if (!cov) continue;
  let n = 0;
  for (const ln of addedSet) if (cov.has(ln)) n++;
  if (n > 0) {
    dupChangedLines += n;
    offenders.push([file, n]);
  }
}

const density =
  changedLines === 0 ? 0 : (dupChangedLines / changedLines) * 100;
console.log(
  `Duplication on changed lines (estimate vs ${BASE}): ${density.toFixed(2)}%  ` +
    `(${dupChangedLines}/${changedLines} changed lines in duplicated blocks)`,
);
if (offenders.length) {
  console.log("Files contributing duplicated changed lines:");
  for (const [f, n] of offenders.sort((a, b) => b[1] - a[1])) {
    console.log(`  ${String(n).padStart(4)}  ${f}`);
  }
}
console.log(`Limit: <= ${THRESHOLD}% (SonarCloud is authoritative).`);

if (density > THRESHOLD) {
  console.error(
    `\nDuplication on changed lines ${density.toFixed(2)}% exceeds the ` +
      `${THRESHOLD}% limit. Dedupe the files listed above.`,
  );
  process.exit(1);
}
