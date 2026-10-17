/**
 * `gaia update` flow.
 *
 * Default (release) mode moves an install to the GAIA release this CLI ships:
 * infra/docker is checked out at the CLI's git tag, GAIA_VERSION in
 * infra/docker/.env is pinned to the matching image tag, the images are
 * pulled and the stack restarts. `--git` keeps the developer path: pull the
 * checkout's branch and rebuild the images from source. Neither mode ever
 * runs `down -v`, so volumes survive.
 * @module commands/update/flow
 */

import { execa } from "execa";
import {
  readDockerComposePortOverrides,
  readPinnedGaiaVersion,
} from "../../lib/env-writer.js";
import type { ReleaseImageGap } from "../../lib/image-availability.js";
import {
  assertReleaseTagPublished,
  pinReleaseImages,
  releaseGitTag,
} from "../../lib/release.js";
import {
  pullSelfhostImages,
  startServices,
} from "../../lib/service-starter.js";
import { isNewerRelease, releaseVersion } from "../../lib/update-check.js";

/** Paths whose change matters for a self-host deploy. */
export const WATCH_PATHS = ["apps/web", "apps/api", "infra/docker"] as const;

/** What changed between two git refs, limited to {@link WATCH_PATHS}. */
export interface ChangeSummary {
  commits: string[];
}

/** What `gaia update` does about a release, decided before anything changes. */
export type ReleaseDecision =
  /** The install runs a non-release build (latest, a commit) and no --version named one. */
  | { kind: "development-build" }
  /** The target is not newer than what runs, and no --version asked for it. */
  | { kind: "up-to-date" }
  /** The target's images are missing for this computer. */
  | { kind: "unavailable"; gap: ReleaseImageGap }
  | { kind: "offer"; downgrade: boolean };

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

/** Where a release-mode update moves the install from and to. */
export interface ReleasePlan {
  repoPath: string;
  fromVersion: string;
  toVersion: string;
  /** The infra checkout move; null when the install is not a git checkout. */
  checkout: {
    fromRef: string;
    toTag: string;
    atTag: boolean;
  } | null;
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
 * @throws Error naming the tag when origin has no git tag for this CLI release.
 */
export async function planReleaseUpdate(
  repoPath: string,
  toVersion: string,
): Promise<ReleasePlan> {
  const fromVersion = readPinnedGaiaVersion(repoPath);
  const toTag = releaseGitTag(toVersion);
  if (!(await isGitCheckout(repoPath))) {
    return { repoPath, fromVersion, toVersion, checkout: null };
  }

  await assertReleaseTagPublished("origin", toVersion, repoPath);
  const tagRef = `refs/tags/${toTag}`;
  const fetched = await execa(
    "git",
    ["fetch", "--no-tags", "origin", `+${tagRef}:${tagRef}`],
    { cwd: repoPath, reject: false },
  );
  if (fetched.exitCode !== 0) {
    throw new Error(
      `Could not fetch ${toTag} from origin: ${fetched.stderr.trim()}`,
    );
  }

  const [head, tagCommit, fromRef] = await Promise.all([
    git(repoPath, ["rev-parse", "HEAD"]),
    git(repoPath, ["rev-parse", `${toTag}^{commit}`]),
    git(repoPath, ["rev-parse", "--short", "HEAD"]),
  ]);
  return {
    repoPath,
    fromVersion,
    toVersion,
    checkout: {
      fromRef,
      toTag,
      atTag: head === tagCommit,
    },
  };
}

/** True when the install already runs this release's images and infra files. */
export function isReleaseCurrent(plan: ReleasePlan): boolean {
  return (
    plan.fromVersion === plan.toVersion &&
    (plan.checkout === null || plan.checkout.atTag)
  );
}

/**
 * Pull the release's images, then check out its infra files, pin the tag and
 * restart. A missing tag fails at the pull, before the install changes.
 * @throws Error listing the files when tracked files carry local changes.
 */
export async function applyReleaseUpdate(
  plan: ReleasePlan,
  onStatus: (message: string) => void,
): Promise<void> {
  if (plan.checkout && !plan.checkout.atTag) {
    const dirty = lines(
      await git(plan.repoPath, [
        "status",
        "--porcelain",
        "--untracked-files=no",
      ]),
    );
    if (dirty.length > 0) {
      throw new Error(
        `Local changes to tracked files would be overwritten:\n  ${dirty.join("\n  ")}\n` +
          "Commit or discard them, or update this checkout yourself with 'gaia update --git'.",
      );
    }
  }

  onStatus(`Downloading GAIA ${plan.toVersion}…`);
  await pullSelfhostImages(plan.repoPath, plan.toVersion);

  if (plan.checkout && !plan.checkout.atTag) {
    onStatus(`Updating the setup files to ${plan.toVersion}…`);
    await git(plan.repoPath, ["checkout", "--detach", plan.checkout.toTag]);
  }

  onStatus(`Switching to GAIA ${plan.toVersion}…`);
  pinReleaseImages(plan.repoPath, plan.toVersion);

  onStatus("Restarting GAIA…");
  await startServices(
    plan.repoPath,
    "selfhost",
    onStatus,
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
