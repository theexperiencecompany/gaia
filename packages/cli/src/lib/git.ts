/**
 * Git operations for repository setup and cloning.
 * @module git
 */

import { execa } from "execa";
import fs from "fs";
import simpleGit from "simple-git";

/**
 * Progress information during git clone operation.
 * @internal Used internally for progress tracking
 */
export interface CloneProgress {
  /** Current progress percentage (0-100) */
  progress: number;
  /** Current phase of the clone operation */
  phase: "counting" | "compressing" | "receiving" | "resolving" | "complete";
  /** Optional details about the current operation */
  details?: string;
}

/**
 * Progress callback function type.
 * @param progress - Current progress percentage (0-100)
 * @param phase - Optional description of the current phase
 */
type ProgressCallback = (progress: number, phase?: string) => void;

/**
 * Sets up a repository by cloning or pulling updates.
 * Provides real-time progress updates during the clone operation.
 * @param targetDir - Directory to clone into
 * @param repoUrl - Git repository URL to clone from
 * @param onProgress - Callback function for progress updates
 * @throws Error if git clone fails
 * @example
 * await setupRepo('./my-repo', 'https://github.com/org/repo.git', (progress, phase) => {
 *   console.log(`${progress}% - ${phase}`);
 * });
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

      // Git progress is written to stderr
      gitProcess.stderr?.on("data", (data: Buffer) => {
        const output = data.toString();

        // Check for different phases
        if (output.includes("Counting objects")) {
          onProgress(5, "Counting objects");
        } else if (output.includes("Compressing objects")) {
          onProgress(10, "Compressing objects");
        }

        // Parse git progress output
        // Format: "Receiving objects: XX% (N/M)"
        const receivingMatch = output.match(
          /Receiving objects:\s+(\d+)%\s+\((\d+)\/(\d+)\)/,
        );
        if (receivingMatch?.[1]) {
          const percent = Math.min(100, parseInt(receivingMatch[1], 10));
          const current = receivingMatch[2];
          const total = receivingMatch[3];
          // Receiving is 10-60% of total progress
          onProgress(
            10 + Math.floor(percent * 0.5),
            `Receiving objects: ${current}/${total}`,
          );
        }

        // Format: "Resolving deltas: XX% (N/M)"
        const resolvingMatch = output.match(
          /Resolving deltas:\s+(\d+)%\s+\((\d+)\/(\d+)\)/,
        );
        if (resolvingMatch?.[1]) {
          const percent = Math.min(100, parseInt(resolvingMatch[1], 10));
          const current = resolvingMatch[2];
          const total = resolvingMatch[3];
          // Resolving is 60-100% of total progress
          onProgress(
            60 + Math.floor(percent * 0.4),
            `Resolving deltas: ${current}/${total}`,
          );
        }
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
