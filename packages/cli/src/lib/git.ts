/**
 * Git operations for repository setup and cloning.
 * @module git
 */

import { execa } from "execa";
import fs from "fs";
import simpleGit from "simple-git";

/**
 * Progress callback function type.
 * @param progress - Current progress percentage (0-100)
 * @param phase - Optional description of the current phase
 */
type ProgressCallback = (progress: number, phase?: string) => void;

/** Share of the overall clone bar the download takes; unpacking fills the rest. */
const DOWNLOAD_SHARE = 0.85;

const RECEIVING_RE =
  /Receiving objects:\s+(\d+)%[^,\r\n]*(?:,\s*([\d.]+\s*[KMG]iB))?/g;
const RESOLVING_RE = /Resolving deltas:\s+(\d+)%/g;

/**
 * The newest progress in a chunk of `git clone --progress` output, as one
 * overall percentage and a plain label, e.g. "52.18 MiB downloaded".
 */
export function parseCloneProgress(
  output: string,
): { percent: number; label: string } | null {
  const resolving = [...output.matchAll(RESOLVING_RE)].at(-1);
  if (resolving?.[1]) {
    const pct = Number(resolving[1]);
    return {
      percent: Math.floor(DOWNLOAD_SHARE * 100 + pct * (1 - DOWNLOAD_SHARE)),
      label: "Unpacking the files",
    };
  }
  const receiving = [...output.matchAll(RECEIVING_RE)].at(-1);
  if (receiving?.[1]) {
    const pct = Number(receiving[1]);
    const size = receiving[2]?.replace(/\s+/, " ");
    return {
      percent: Math.floor(pct * DOWNLOAD_SHARE),
      label: size ? `${size} downloaded` : "Downloading",
    };
  }
  return null;
}

/**
 * Sets up a repository by cloning or pulling updates, reporting progress via `onProgress`.
 *
 * @throws Error if git clone fails.
 */
export async function setupRepo(
  targetDir: string,
  repoUrl: string,
  onProgress: ProgressCallback,
  branch?: string,
): Promise<void> {
  if (fs.existsSync(targetDir)) {
    const gitDir = `${targetDir}/.git`;
    if (!fs.existsSync(gitDir)) {
      throw new Error(
        `Directory ${targetDir} exists but is not a git repository`,
      );
    }
    const git = simpleGit();
    await git.cwd(targetDir).pull();
    onProgress(100, "Already exists, pulled latest");
  } else {
    try {
      // Use execa to run git with progress output
      const cloneArgs = ["clone", "--progress"];
      if (branch) {
        cloneArgs.push("--branch", branch);
      }
      cloneArgs.push(repoUrl, targetDir);

      const gitProcess = execa("git", cloneArgs);

      // Git writes progress to stderr, several \r-separated updates per chunk.
      gitProcess.stderr?.on("data", (data: Buffer) => {
        const progress = parseCloneProgress(data.toString());
        if (progress) onProgress(progress.percent, progress.label);
      });

      await gitProcess;
      onProgress(100, "Clone complete");
    } catch (error) {
      if (fs.existsSync(targetDir)) {
        fs.rmSync(targetDir, { recursive: true, force: true });
      }
      throw error;
    }
  }
}
