/**
 * `gaia update` flow.
 *
 * Default (release) mode moves an install to the GAIA release this CLI ships:
 * that release's setup files (the bundle) replace the install's, GAIA_VERSION
 * in infra/docker/.env is pinned to the matching image tag, the images are
 * pulled and the stack restarts. An install `gaia up` once made as a git
 * checkout moves to release files the same way: its tracked files and .git go,
 * the settings and backups beside them stay. `--git` keeps the developer path:
 * pull the checkout's branch and rebuild the images from source. Neither mode
 * ever runs `down -v`, so volumes survive.
 * @module commands/update/flow
 */

import * as fsp from "node:fs/promises";
import { execa } from "execa";
import {
  readDockerComposePortOverrides,
  readPinnedGaiaVersion,
} from "../../lib/env-writer.js";
import type { ReleaseImageGap } from "../../lib/image-availability.js";
import { pinReleaseImages, releaseGitTag } from "../../lib/release.js";
import {
  checkoutOwnedFiles,
  placeBundle,
  readBundleManifest,
  stageBundle,
} from "../../lib/selfhost-bundle.js";
import {
  pullSelfhostImages,
  startServices,
} from "../../lib/service-starter.js";
import { isNewerRelease, releaseVersion } from "../../lib/update-check.js";
import type {
  ChangeSummary,
  InstallLayout,
  ReleaseDecision,
  ReleasePlan,
  ReleaseUpdateReporter,
} from "./flow.types.js";

/** Paths whose change matters for a self-host deploy. */
export const WATCH_PATHS = ["apps/web", "apps/api", "infra/docker"] as const;

/**
 * Offer an update only when the target is a newer release whose images exist
 * here; an explicit --version may move anywhere its images exist.
 */
export function decideReleaseUpdate(options: {
  current: string;
  target: string;
  explicit: boolean;
  gap: ReleaseImageGap | null;
}): ReleaseDecision {
  const { current, target, explicit, gap } = options;
  if (!explicit) {
    if (releaseVersion(current) === null) return { kind: "development-build" };
    if (!isNewerRelease(target, current)) return { kind: "up-to-date" };
  }
  if (gap) return { kind: "unavailable", gap };
  return { kind: "offer", downgrade: isNewerRelease(current, target) };
}

async function git(repoPath: string, args: string[]): Promise<string> {
  const { stdout } = await execa("git", args, { cwd: repoPath });
  return stdout.trim();
}

/** True when the install is a git checkout with an origin remote to fetch from. */
async function isGitCheckout(repoPath: string): Promise<boolean> {
  const inside = await execa("git", ["rev-parse", "--is-inside-work-tree"], {
    cwd: repoPath,
    reject: false,
  });
  if (inside.exitCode !== 0 || inside.stdout.trim() !== "true") return false;
  const origin = await execa("git", ["remote", "get-url", "origin"], {
    cwd: repoPath,
    reject: false,
  });
  return origin.exitCode === 0;
}

function lines(stdout: string): string[] {
  return stdout
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

async function summarizeChanges(
  repoPath: string,
  range: string,
): Promise<ChangeSummary> {
  const log = await git(repoPath, [
    "log",
    range,
    "--oneline",
    "--",
    ...WATCH_PATHS,
  ]);
  return { commits: lines(log) };
}

/**
 * Work out a release-mode update without changing anything.
 * @throws Error when the target is not a release, or a checkout cannot move to release files.
 */
export async function planReleaseUpdate(
  repoPath: string,
  toVersion: string,
): Promise<ReleasePlan> {
  releaseGitTag(toVersion);
  const fromVersion = readPinnedGaiaVersion(repoPath);
  const manifest = readBundleManifest(repoPath);
  const layout: InstallLayout = manifest
    ? { kind: "bundle", version: manifest.version, files: manifest.files }
    : { kind: "checkout", files: await checkoutOwnedFiles(repoPath) };
  return { repoPath, fromVersion, toVersion, layout };
}

/** True when the install already runs this release's images and setup files. */
export function isReleaseCurrent(plan: ReleasePlan): boolean {
  return (
    plan.fromVersion === plan.toVersion &&
    plan.layout.kind === "bundle" &&
    plan.layout.version === plan.toVersion
  );
}

/**
 * Get the release's setup files and images, then swap the files in, pin the
 * tag and restart. A release that is missing fails at the download or the
 * pull, before the install changes.
 */
export async function applyReleaseUpdate(
  plan: ReleasePlan,
  report: ReleaseUpdateReporter,
): Promise<void> {
  report.onStatus(`Getting the setup files for GAIA ${plan.toVersion}…`);
  const staged = await stageBundle(
    plan.repoPath,
    plan.toVersion,
    report.onBundleDownload,
  );
  try {
    report.onStatus(`Downloading GAIA ${plan.toVersion}…`);
    await pullSelfhostImages(plan.repoPath, plan.toVersion, report.onImagePull);
  } catch (error) {
    await fsp.rm(staged.stagingDir, { recursive: true, force: true });
    throw error;
  }

  report.onStatus(
    plan.layout.kind === "checkout"
      ? "Moving this install from a git checkout to the release's setup files…"
      : `Switching the setup files to ${plan.toVersion}…`,
  );
  await placeBundle(
    staged.manifest,
    staged.stagingDir,
    plan.repoPath,
    plan.layout.files,
  );
  pinReleaseImages(plan.repoPath, plan.toVersion);

  report.onStatus("Restarting GAIA…");
  await startServices(
    plan.repoPath,
    "selfhost",
    report.onStatus,
    readDockerComposePortOverrides(plan.repoPath),
    undefined,
    { pull: "missing" },
  );
}

/** What `git pull` would bring into a developer checkout's current branch. */
export async function planGitUpdate(repoPath: string): Promise<ChangeSummary> {
  if (!(await isGitCheckout(repoPath))) {
    throw new Error(
      `${repoPath} is not a git checkout with an origin remote; run 'gaia update' without --git.`,
    );
  }
  const branch = await execa("git", ["symbolic-ref", "-q", "--short", "HEAD"], {
    cwd: repoPath,
    reject: false,
  });
  if (branch.exitCode !== 0) {
    throw new Error(
      `${repoPath} is on a release tag, not a branch. Switch to one first: git -C ${repoPath} checkout master`,
    );
  }
  await git(repoPath, ["fetch", "origin"]);
  return summarizeChanges(repoPath, "HEAD..@{upstream}");
}

/** Fast-forward the checkout, then rebuild the images from it and restart. */
export async function applyGitUpdate(
  repoPath: string,
  onStatus: (message: string) => void,
): Promise<void> {
  onStatus("Pulling the latest commits (git pull --ff-only)…");
  await git(repoPath, ["pull", "--ff-only"]);
  onStatus("Rebuilding images from this checkout and restarting…");
  await startServices(
    repoPath,
    "selfhost",
    onStatus,
    readDockerComposePortOverrides(repoPath),
    undefined,
    { build: true },
  );
}
