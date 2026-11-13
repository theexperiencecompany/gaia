#!/usr/bin/env node
/**
 * Refuse to measure a build that is not the commit you asked for.
 *
 * A green `next build` of the wrong revision looks exactly like success. That
 * happened here: a modified local file made `git checkout` abort, the error sat
 * above `BUILD=0` in the log, and the build that got audited was the previous
 * commit. Every number from it was about code nobody had reviewed.
 *
 * Usage:
 *   node scripts/assert-build-sha.mjs            # HEAD is what got built
 *   node scripts/assert-build-sha.mjs <sha>      # ...and it must equal <sha>
 *
 * Exits 0 only when the tree is clean, HEAD matches, and the build output is
 * newer than the last source change.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const expected = process.argv[2] ?? null;
const problems = [];

const git = (...args) => execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();

const head = git("rev-parse", "HEAD");
const short = head.slice(0, 10);

// 1. A dirty tree means the build may contain uncommitted edits.
const dirty = git("status", "--porcelain");
if (dirty) {
  problems.push(
    `working tree is dirty, so the build is not any single commit:\n` +
      dirty
        .split("\n")
        .slice(0, 10)
        .map((l) => `      ${l}`)
        .join("\n"),
  );
}

// 2. The requested revision must be the one checked out.
if (expected) {
  const want = git("rev-parse", "--verify", "--end-of-options", `${expected}^{commit}`).slice(0, 10);
  if (want !== short) {
    problems.push(
      `HEAD is ${short} but ${expected} is ${want} — the build is the wrong revision`,
    );
  }
}

// 3. The build must be newer than the newest tracked source file, or it was
//    produced before those edits and cannot reflect them.
const buildStamp = path.join(ROOT, ".next", "BUILD_ID");
if (fs.existsSync(buildStamp)) {
  const built = fs.statSync(buildStamp).mtimeMs;
  const newest = Number(
    git("log", "-1", "--format=%ct", "HEAD") * 1000,
  );
  if (newest > built) {
    problems.push(
      `HEAD commit is newer than .next/BUILD_ID — the build predates the checkout`,
    );
  }
} else {
  problems.push("no .next/BUILD_ID — nothing has been built in this tree");
}

if (problems.length > 0) {
  console.error(
    [
      "[assert-build-sha] refusing to report numbers for this build:",
      ...problems.map((p) => `  - ${p}`),
      "",
      "Reset, rebuild, then measure:",
      "  git checkout -- . && git checkout -B <branch> FETCH_HEAD",
      "  pnpm exec next build && node scripts/assert-build-sha.mjs <sha>",
    ].join("\n"),
  );
  process.exit(1);
}

console.log(`[assert-build-sha] clean tree, HEAD ${short}, build is current.`);
