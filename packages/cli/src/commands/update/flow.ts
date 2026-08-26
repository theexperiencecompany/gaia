/**
 * `gaia update` flow — drift detection and pull-vs-build decision.
 *
 * v1 keeps it simple: fetch origin, compare HEAD..origin/master for the
 * watch paths, summarize what changed, then `git pull --ff-only` and restart
 * with either `--build` or `--pull always`.  Never runs `down -v` so volumes
 * and infra/docker/.env are preserved.
 * @module commands/update/flow
 */

import { execa } from "execa";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { findRepoRoot, startServices } from "../../lib/service-starter.js";
import type { CheckResult } from "../doctor/types.js";

/** Paths whose change matters for a self-host deploy. */
export const WATCH_PATHS = ["apps/web", "apps/api", "infra/docker"] as const;

/** Files whose change forces a rebuild (web image must be baked). */
export const REBUILD_TRIGGERS = [
  "apps/web/Dockerfile",
  "apps/web/package.json",
] as const;

/** Summary of what `git diff --name-only HEAD..origin/master` reported. */
export interface UpdateStatus {
  repoPath: string;
  behindCount: number;
  changedFiles: string[];
  summary: Record<string, number>;
  needsRebuild: boolean;
  commits: string[];
}

function summarizeFiles(files: string[]): Record<string, number> {
  const summary: Record<string, number> = {};
  for (const file of files) {
    const prefix = WATCH_PATHS.find((p) => file.startsWith(p)) ?? "other";
    summary[prefix] = (summary[prefix] ?? 0) + 1;
  }
  return summary;
}

export function needsRebuildFromFiles(files: string[]): boolean {
  return files.some((f) =>
    REBUILD_TRIGGERS.some((t) => f === t || f.startsWith(t)),
  );
}

/** True when `apps/web` source changed — also used for rebuild heuristic. */
function fileListNeedsRebuild(files: string[]): boolean {
  return needsRebuildFromFiles(files);
}

export async function isGitRepo(repoPath: string): Promise<boolean> {
  try {
    const { stdout } = await execa(
      "git",
      ["rev-parse", "--is-inside-work-tree"],
      {
        cwd: repoPath,
      },
    );
    return stdout.trim() === "true";
  } catch {
    return false;
  }
}

export async function hasGitRemote(
  repoPath: string,
  remote = "origin",
): Promise<boolean> {
  try {
    await execa("git", ["remote", "get-url", remote], { cwd: repoPath });
    return true;
  } catch {
    return false;
  }
}

export async function fetchOrigin(repoPath: string): Promise<void> {
  if (!(await isGitRepo(repoPath))) {
    throw new Error("Not a git repository — pull manually");
  }
  if (!(await hasGitRemote(repoPath))) {
    throw new Error("Not a git repository — pull manually (no origin remote)");
  }
  await execa("git", ["fetch", "origin"], { cwd: repoPath });
}

export async function getBehindCount(repoPath: string): Promise<number> {
  try {
    const { stdout } = await execa(
      "git",
      ["rev-list", "HEAD..origin/master", "--count"],
      { cwd: repoPath },
    );
    const n = Number(stdout.trim());
    return Number.isFinite(n) ? n : 0;
  } catch {
    return 0;
  }
}

export async function getChangedFiles(repoPath: string): Promise<string[]> {
  try {
    const { stdout } = await execa(
      "git",
      ["diff", "--name-only", "HEAD..origin/master", "--", ...WATCH_PATHS],
      { cwd: repoPath },
    );
    return stdout
      .trim()
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  } catch {
    return [];
  }
}

export async function getCommits(repoPath: string): Promise<string[]> {
  try {
    const { stdout } = await execa(
      "git",
      ["log", "HEAD..origin/master", "--oneline", "--", ...WATCH_PATHS],
      { cwd: repoPath },
    );
    return stdout
      .trim()
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  } catch {
    return [];
  }
}

export async function getUpdateStatus(repoPath: string): Promise<UpdateStatus> {
  const behindCount = await getBehindCount(repoPath);
  const changedFiles = await getChangedFiles(repoPath);
  const commits = await getCommits(repoPath);
  return {
    repoPath,
    behindCount,
    changedFiles,
    summary: summarizeFiles(changedFiles),
    needsRebuild: fileListNeedsRebuild(changedFiles),
    commits,
  };
}

/**
 * Doctor check: warns when the local checkout is behind origin/master.
 * Never fetches — uses the locally cached origin/master to avoid network
 * delay in `gaia doctor`. The `gaia update` command does the fetch.
 *
 * Returns `skipped` (not `fail`) when the install is not a git repo (e.g.
 * `gaia-vm` plain copy) — that is an expected self-host artifact, not a
 * broken state.
 */
export async function checkUpdateAvailable(): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "git-update",
    label: "Git update",
    severity: "warning",
  };

  const repoPath = findRepoRoot();
  if (!repoPath) {
    return {
      ...base,
      state: "skipped",
      detail: "No GAIA installation found",
    };
  }

  if (!(await isGitRepo(repoPath))) {
    return {
      ...base,
      state: "skipped",
      detail: "Not a git repository — pull manually",
    };
  }
  if (!(await hasGitRemote(repoPath))) {
    return {
      ...base,
      state: "skipped",
      detail: "Not a git repository — pull manually (no origin remote)",
    };
  }

  try {
    const { stdout } = await execa(
      "git",
      ["rev-list", "HEAD..origin/master", "--count"],
      { cwd: repoPath },
    );
    const count = Number(stdout.trim());
    if (!Number.isFinite(count)) {
      return {
        ...base,
        state: "skipped",
        detail: "Could not check git status",
      };
    }
    if (count === 0) {
      return { ...base, state: "ok", detail: "Up to date with origin/master" };
    }
    return {
      ...base,
      state: "fail",
      detail: `${count} commit(s) behind origin/master`,
      fix: "Run 'gaia update' to pull and restart services (preserves infra/docker/.env and volumes).",
    };
  } catch {
    return {
      ...base,
      state: "skipped",
      detail: "Could not check git status (no origin/master or not a git repo)",
    };
  }
}

/**
 * Perform the pull and restart. Caller should have already confirmed the
 * update (or passed --yes). Preserves infra/docker/.env and volumes (never
 * runs `down -v`).
 *
 * If the repo is not a git checkout (gaia-vm plain copy) the pull is skipped
 * with a clear message instead of crashing on `git rev-parse`.
 */
export async function pullAndRestart(
  repoPath: string,
  needsRebuild: boolean,
  onStatus?: (msg: string) => void,
): Promise<void> {
  if (!(await isGitRepo(repoPath))) {
    throw new Error("Not a git repository — pull manually");
  }
  if (!(await hasGitRemote(repoPath))) {
    throw new Error("Not a git repository — pull manually (no origin remote)");
  }
  onStatus?.("Pulling latest changes (git pull --ff-only)...");
  try {
    await execa("git", ["pull", "--ff-only"], { cwd: repoPath });
  } catch (e) {
    const msg = (e as Error).message;
    // `--ff-only` refuses when history diverged or local changes would be
    // overwritten. Surface the git hint rather than a raw execa dump, and let
    // the caller (handler) suggest stashing/committing.
    if (
      msg.includes("Not possible to fast-forward") ||
      msg.includes("would be overwritten") ||
      msg.includes("divergent")
    ) {
      throw e;
    }
    throw e;
  }

  const portOverrides = readDockerComposePortOverrides(repoPath);
  onStatus?.(
    needsRebuild
      ? "Web Dockerfile or package.json changed — rebuilding images (this can take 5-30 min on 4 GB RAM, please wait)..."
      : "Restarting services with latest images (pull always)...",
  );

  await startServices(
    repoPath,
    "selfhost",
    onStatus,
    portOverrides,
    (chunk) => {
      // Stream docker output to status lines is not needed; startServices
      // already handles logs. This keeps the update flow quiet.
      void chunk;
    },
    needsRebuild ? { build: true } : { pull: true },
  );
  onStatus?.("Update complete — services restarted.");
}
