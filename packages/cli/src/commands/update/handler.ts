/**
 * Handler for `gaia update` — show what an update changes, confirm, apply.
 * @module commands/update/handler
 */

import * as readline from "node:readline";
import { isInteractive } from "../../lib/non-tty.js";
import { newerReleaseHint } from "../../lib/release.js";
import { findInstallRoot } from "../../lib/service-starter.js";
import { CLI_VERSION, GAIA_RELEASE_IMAGE_TAG } from "../../lib/version.js";
import {
  applyGitUpdate,
  applyReleaseUpdate,
  type ChangeSummary,
  isReleaseCurrent,
  planGitUpdate,
  planReleaseUpdate,
  type ReleasePlan,
} from "./flow.js";

export interface UpdateOptions {
  yes?: boolean;
  /** Image tag to pin instead of the one this CLI release ships. */
  version?: string;
  /** Developer checkouts: pull the branch and rebuild from source. */
  git?: boolean;
}

const MAX_LISTED_COMMITS = 10;
const RELEASE_NOTES_URL = "https://docs.heygaia.io/release-notes";

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

function err(line = ""): void {
  process.stderr.write(`${line}\n`);
}

async function askConfirm(question: string): Promise<boolean> {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  const answer = await new Promise<string>((resolve) => {
    rl.question(question, (ans) => resolve(ans));
  });
  rl.close();
  const normalized = answer.trim().toLowerCase();
  return normalized === "" || normalized === "y" || normalized === "yes";
}

function printChanges(changes: ChangeSummary): void {
  for (const [prefix, count] of Object.entries(changes.files)) {
    out(`    ${prefix}: ${count} file(s)`);
  }
  for (const commit of changes.commits.slice(0, MAX_LISTED_COMMITS)) {
    out(`    ${commit}`);
  }
  if (changes.commits.length > MAX_LISTED_COMMITS) {
    out(`    ... and ${changes.commits.length - MAX_LISTED_COMMITS} more`);
  }
}

function printReleasePlan(plan: ReleasePlan): void {
  out(`\nGAIA images: ${plan.fromVersion} -> ${plan.toVersion}`);
  if (plan.checkout === null) {
    out(
      "Compose files: unchanged (this install is not a git checkout; replace infra/docker by hand if the release changed it)",
    );
    return;
  }
  if (plan.checkout.atTag) {
    out(`Compose files: already at ${plan.checkout.toTag}`);
    return;
  }
  out(`Compose files: ${plan.checkout.fromRef} -> ${plan.checkout.toTag}`);
  printChanges(plan.checkout.changes);
}

/** Ask unless --yes; a non-interactive run without --yes only reports. */
async function confirmed(options: UpdateOptions): Promise<boolean> {
  if (options.yes) return true;
  if (!isInteractive()) {
    out("\nNon-interactive terminal: rerun with --yes to apply.");
    return false;
  }
  return askConfirm("\nApply and restart now? [Y/n] ");
}

async function runReleaseUpdate(
  repoPath: string,
  options: UpdateOptions,
): Promise<void> {
  const plan = await planReleaseUpdate(
    repoPath,
    options.version ?? GAIA_RELEASE_IMAGE_TAG,
  );
  if (isReleaseCurrent(plan)) {
    out(`Already on GAIA ${plan.toVersion}.`);
    for (const line of newerReleaseHint(CLI_VERSION)) out(line);
    return;
  }
  printReleasePlan(plan);
  out("Volumes, apps/api/.env and infra/docker/.env are kept.");
  if (!(await confirmed(options))) return;

  await applyReleaseUpdate(plan, (message) => out(`  ${message}`));
  out(`\nGAIA is on ${plan.toVersion}. What's new: ${RELEASE_NOTES_URL}`);
  out("Run 'gaia doctor' to confirm every dependency is ready.");
}

async function runGitUpdate(
  repoPath: string,
  options: UpdateOptions,
): Promise<void> {
  const changes = await planGitUpdate(repoPath);
  if (changes.commits.length === 0) {
    out("Already up to date with the upstream branch.");
    return;
  }
  out(`\n${changes.commits.length} new commit(s) touch the self-host stack:`);
  printChanges(changes);
  out("The images are rebuilt from this checkout (slow on small machines).");
  if (!(await confirmed(options))) return;

  await applyGitUpdate(repoPath, (message) => out(`  ${message}`));
  out("\nUpdated and restarted from source.");
}

export async function runUpdate(options: UpdateOptions = {}): Promise<void> {
  const repoPath = findInstallRoot();
  if (!repoPath) {
    err("Error: No GAIA installation found.");
    err("Fix: Run 'gaia up' to install GAIA first.");
    process.exitCode = 1;
    return;
  }
  if (options.git && options.version) {
    err(
      "Error: --version pins published images; --git builds from source. Pick one.",
    );
    process.exitCode = 1;
    return;
  }

  out(`Checking for updates in ${repoPath}...`);
  try {
    await (options.git
      ? runGitUpdate(repoPath, options)
      : runReleaseUpdate(repoPath, options));
  } catch (e) {
    err(`\nUpdate failed: ${(e as Error).message}`);
    err(
      "Volumes are untouched. Fix the cause above, then rerun 'gaia update'.",
    );
    process.exitCode = 1;
  }
}
