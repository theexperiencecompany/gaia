/**
 * Handler for `gaia update` — drift detection, pull, and restart.
 * @module commands/update/handler
 */

import * as readline from "node:readline";
import { execa } from "execa";
import { isInteractive } from "../../lib/non-tty.js";
import { findRepoRoot } from "../../lib/service-starter.js";
import {
  fetchOrigin,
  getUpdateStatus,
  pullAndRestart,
  WATCH_PATHS,
} from "./flow.js";

export interface UpdateOptions {
  yes?: boolean;
}

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

function printManualSteps(): void {
  out("\nManual update steps (preserves infra/docker/.env and volumes):");
  out("  git fetch origin");
  out("  git log HEAD..origin/master --oneline -- apps/web apps/api infra/docker  # what changed");
  out("  git pull --ff-only");
  out("  # if apps/web/Dockerfile or apps/web/package.json changed:");
  out("  gaia up --build");
  out("  # otherwise:");
  out("  gaia up   # or: docker compose -f infra/docker/docker-compose.selfhost.yml up -d --pull always");
  out("  # never run: docker compose down -v  (would delete volumes)");
}

export async function runUpdate(options: UpdateOptions = {}): Promise<void> {
  const repoPath = findRepoRoot();
  if (!repoPath) {
    err("Error: No GAIA installation found.");
    err("Fix: Run 'gaia up' or 'gaia init' to clone the repository first.");
    process.exitCode = 1;
    return;
  }

  out(`Checking for updates in ${repoPath}...`);
  try {
    await fetchOrigin(repoPath);
  } catch (e) {
    err(`Warning: Could not fetch origin: ${(e as Error).message}`);
    err("Fix: Check your network and that 'origin' remote is configured (git remote -v).");
    printManualSteps();
    process.exitCode = 1;
    return;
  }

  let status;
  try {
    status = await getUpdateStatus(repoPath);
  } catch (e) {
    err(`Error checking update status: ${(e as Error).message}`);
    process.exitCode = 1;
    return;
  }

  // No diff in watch paths but maybe behindCount >0 for other paths — still
  // report as up-to-date for the self-host watch set, matching spec's log filter.
  if (status.changedFiles.length === 0 && status.behindCount === 0) {
    out("Already up to date.");
    return;
  }
  if (status.changedFiles.length === 0 && status.behindCount > 0) {
    out(`Already up to date for ${WATCH_PATHS.join(", ")} (${status.behindCount} commit(s) behind on other paths).`);
    return;
  }

  out(`\nUpdate available — ${status.behindCount} commit(s) behind origin/master:`);
  for (const [prefix, count] of Object.entries(status.summary)) {
    const label = prefix === "other" ? "other" : prefix;
    out(`  ${label}: ${count} file(s)`);
    // Extra hint for compose changes
    if (prefix === "infra/docker" && status.changedFiles.some((f) => f.includes("compose"))) {
      out("    (compose file changed)");
    }
  }
  if (status.commits.length > 0) {
    out("\nCommits:");
    for (const c of status.commits.slice(0, 10)) {
      out(`  ${c}`);
    }
    if (status.commits.length > 10) {
      out(`  ... and ${status.commits.length - 10} more`);
    }
  }
  out(`\nStrategy: ${status.needsRebuild ? "--build (Dockerfile/package.json changed)" : "--pull always"}`);
  out("Preserves infra/docker/.env and volumes (never runs down -v).");

  let confirmed = options.yes === true;
  if (!confirmed) {
    if (!isInteractive()) {
      out("\nNon-interactive terminal — re-run with --yes to apply, or run manually:");
      printManualSteps();
      return;
    }
    confirmed = await askConfirm("\nPull and restart now? [Y/n] ");
    if (!confirmed) {
      out("Aborted. Run 'gaia update --yes' to apply, or manually:");
      printManualSteps();
      return;
    }
  }

  try {
    await pullAndRestart(repoPath, status.needsRebuild, (msg) => out(`  ${msg}`));
    out("\nAlready up to date after pull — services restarted.");
    if (status.needsRebuild) {
      out("Rebuilt images locally (preserved infra/docker/.env and volumes).");
    } else {
      out("Pulled latest images (preserved infra/docker/.env and volumes).");
    }
  } catch (e) {
    // Provide the manual fallback on any failure after fetch.
    const msg = (e as Error).message;
    err(`\nUpdate failed: ${msg}`);
    if (msg.includes("Not possible to fast-forward") || msg.includes("would be overwritten")) {
      err("Fix: Commit or stash local changes, then rerun 'gaia update --yes'.");
    }
    // Show what the user would have run.
    try {
      const { stdout } = await execa("git", ["status", "--porcelain"], { cwd: repoPath });
      if (stdout.trim().length > 0) {
        err("Local modifications exist — 'git pull --ff-only' refuses to overwrite them.");
      }
    } catch {
      // ignore
    }
    printManualSteps();
    process.exitCode = 1;
  }
}
