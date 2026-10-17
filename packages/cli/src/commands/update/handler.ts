/**
 * Handler for `gaia update` — say whether a newer release is available here,
 * confirm, apply.
 * @module commands/update/handler
 */

import * as readline from "node:readline";
import { explainImageGap } from "../../lib/compose-failure.js";
import { readConfig } from "../../lib/config.js";
import { readPinnedGaiaVersion } from "../../lib/env-writer.js";
import { SIGINT_EXIT_CODE } from "../../lib/exit-codes.js";
import { findReleaseImageGap } from "../../lib/image-availability.js";
import { isInteractive } from "../../lib/non-tty.js";
import { homeRelative } from "../../lib/paths.js";
import { printError } from "../../lib/print-error.js";
import { newerReleaseHint } from "../../lib/release.js";
import { fetchReleaseHighlights } from "../../lib/release-notes.js";
import { findInstallRoot } from "../../lib/service-starter.js";
import { wrapForTerminal } from "../../lib/terminal-text.js";
import {
  displayTag,
  isNewerRelease,
  releaseVersion,
} from "../../lib/update-check.js";
import { CLI_VERSION, GAIA_RELEASE_IMAGE_TAG } from "../../lib/version.js";
import { MARK } from "../../ui/constants.js";
import { printHeader } from "../../ui/header/header-lines.js";
import {
  applyGitUpdate,
  applyReleaseUpdate,
  type ChangeSummary,
  decideReleaseUpdate,
  isReleaseCurrent,
  planGitUpdate,
  planReleaseUpdate,
} from "./flow.js";

export interface UpdateOptions {
  yes?: boolean;
  /** Image tag to pin instead of the one this CLI release ships. */
  version?: string;
  /** Developer checkouts: pull the branch and rebuild from source. */
  git?: boolean;
  /** --git: list every new commit, not the first few. */
  verbose?: boolean;
}

const MAX_LISTED_COMMITS = 5;
const RELEASE_NOTES_URL = "https://docs.heygaia.io/release-notes";

function out(line = ""): void {
  process.stdout.write(`${wrapForTerminal(line)}\n`);
}

/** A yes/no question that defaults to no: an update never starts on a stray Enter. */
async function askConfirm(question: string): Promise<boolean> {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  rl.on("SIGINT", () => {
    rl.close();
    out(`\n${MARK.cancelled} Cancelled · nothing changed.`);
    process.exit(SIGINT_EXIT_CODE);
  });
  const answer = await new Promise<string>((resolve) => {
    rl.question(`${question} [y/N] `, (ans) => resolve(ans));
  });
  rl.close();
  const normalized = answer.trim().toLowerCase();
  return normalized === "y" || normalized === "yes";
}

function printChanges(changes: ChangeSummary, verbose: boolean): void {
  const shown = verbose
    ? changes.commits
    : changes.commits.slice(0, MAX_LISTED_COMMITS);
  for (const commit of shown) out(`    ${commit}`);
  const hidden = changes.commits.length - shown.length;
  if (hidden > 0) out(`    and ${hidden} more (--verbose lists them)`);
}

/** What the release changes, from its GitHub release; a failed read says so and moves on. */
async function printHighlights(tag: string): Promise<void> {
  try {
    for (const highlight of await fetchReleaseHighlights(tag)) {
      out(`  - ${highlight}`);
    }
  } catch (error) {
    out(`  (couldn't read what's new in ${tag}: ${(error as Error).message})`);
  }
}

/** Ask unless --yes; a non-interactive run without --yes only reports. */
async function confirmed(
  options: UpdateOptions,
  question: string,
): Promise<boolean> {
  if (options.yes) return true;
  if (!isInteractive()) {
    out("\nNo terminal to confirm in: rerun with --yes to apply.");
    return false;
  }
  return askConfirm(`\n${question}`);
}
async function runReleaseUpdate(
  repoPath: string,
  options: UpdateOptions,
): Promise<void> {
  const current = readPinnedGaiaVersion(repoPath);
  const target = options.version ?? GAIA_RELEASE_IMAGE_TAG;
  const explicit = options.version !== undefined;
  // Only a target that would be offered is worth a registry round trip.
  const worthChecking =
    explicit ||
    (releaseVersion(current) !== null && isNewerRelease(target, current));
  const gap = worthChecking
    ? await findReleaseImageGap(target, readConfig()?.bots ?? [])
    : null;
  const decision = decideReleaseUpdate({ current, target, explicit, gap });

  switch (decision.kind) {
    case "development-build":
      out(
        `This install runs a development build of GAIA (${displayTag(current)}), not a release, so there is nothing to update.`,
      );
      out(
        `To switch it to the ${target} release: gaia update --version ${target}`,
      );
      return;
    case "up-to-date":
      out(`GAIA ${current} is up to date.`);
      for (const line of newerReleaseHint(CLI_VERSION)) out(line);
      return;
    case "unavailable":
      out(
        `${explainImageGap(decision.gap, "gaia up --build").cause} Nothing was changed.`,
      );
      if (explicit) process.exitCode = 1;
      return;
    case "offer":
      break;
  }

  const plan = await planReleaseUpdate(repoPath, target);
  if (isReleaseCurrent(plan)) {
    out(`GAIA ${current} is up to date.`);
    return;
  }
  out(
    decision.downgrade
      ? `\nSwitch GAIA ${current} back to ${target}`
      : `\nUpdate available: GAIA ${current} → ${target}`,
  );
  await printHighlights(target);
  out(`What's new: ${RELEASE_NOTES_URL}`);
  out("Your data and settings are kept.");
  if (!(await confirmed(options, "Update and restart now?"))) return;

  await applyReleaseUpdate(plan, (message) => out(`  ${message}`));
  out(`\n${MARK.ok} GAIA is on ${target}.`);
  out("Run 'gaia doctor' to check that everything is ready.");
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
  printChanges(changes, options.verbose === true);
  out("The images are rebuilt from this checkout (slow on small machines).");
  if (!(await confirmed(options, "Pull, rebuild and restart now?"))) return;

  await applyGitUpdate(repoPath, (message) => out(`  ${message}`));
  out("\nUpdated and restarted from source.");
}

export async function runUpdate(options: UpdateOptions = {}): Promise<void> {
  await printHeader({ showUpdate: false });
  const repoPath = findInstallRoot();
  if (!repoPath) {
    printError(
      "GAIA isn't installed here, so there is nothing to update.\nInstall it with 'gaia up'.",
    );
    process.exitCode = 1;
    return;
  }
  if (options.git && options.version) {
    printError(
      "--version and --git can't be used together.\n--version moves to a published release; --git builds from source. Pick one.",
    );
    process.exitCode = 1;
    return;
  }

  out(`Checking for updates in ${homeRelative(repoPath)}…`);
  try {
    await (options.git
      ? runGitUpdate(repoPath, options)
      : runReleaseUpdate(repoPath, options));
  } catch (e) {
    out();
    printError(
      `GAIA wasn't updated: ${(e as Error).message}\nYour data is untouched. Fix the cause above, then run 'gaia update' again.`,
    );
    process.exitCode = 1;
  }
}
