/**
 * The memory and disk the self-host stack needs, and how this machine
 * measures up. `gaia up` and `gaia doctor` both judge with these, so they can
 * never disagree about whether GAIA fits.
 * @module lib/host-resources
 */

import * as fs from "node:fs";
import * as os from "node:os";
import { execa } from "execa";

const GIB = 1024 ** 3;

/** v0.7.0-beta.8's eight images: 10.0 GB unpacked, plus 2.8 GB of compressed layers held while pulling. */
export const RELEASE_IMAGES_DISK_BYTES = 13 * GIB;
/** Free space an install keeps for its databases, logs and model cache. */
export const DATA_DISK_MIN_BYTES = 2 * GIB;
export const DATA_DISK_RECOMMENDED_BYTES = 5 * GIB;

/** The booted stack holds 5.4 GB (API 2.6, worker 2.4, the rest 0.4) and peaks at 6.4 GB on boot. */
export const MEMORY_MIN_BYTES = 6 * GIB;
/** An "8 GB" machine reports about 7.6 GB to the kernel. */
export const MEMORY_RECOMMENDED_BYTES = 7.5 * GIB;

export type ResourceLevel = "ok" | "warn" | "fail";

export interface ResourceVerdict {
  level: ResourceLevel;
  detail: string;
  fix?: string;
}

/** A fresh install still has to download the images; a running one only grows its data. */
export type DiskPurpose = "install" | "run";

/** Where Docker runs, for the memory fix: a Mac's VM, WSL's VM, or the machine itself. */
export interface MemoryHost {
  platform: NodeJS.Platform;
  wsl: boolean;
}

/** This machine as a MemoryHost; WSL 2's kernel names itself "microsoft". */
export function thisMemoryHost(): MemoryHost {
  return {
    platform: os.platform(),
    wsl: os.platform() === "linux" && /microsoft/i.test(os.release()),
  };
}

function gb(bytes: number): string {
  return `${(bytes / GIB).toFixed(1)} GB`;
}

export function judgeDisk(
  freeBytes: number,
  rootDir: string,
  purpose: DiskPurpose,
): ResourceVerdict {
  const images = purpose === "install" ? RELEASE_IMAGES_DISK_BYTES : 0;
  const free = `${gb(freeBytes)} free at ${rootDir}`;
  const fix =
    "Free up space ('docker system prune' removes unused images and build cache), then try again.";
  if (freeBytes < images + DATA_DISK_MIN_BYTES) {
    return {
      level: "fail",
      detail:
        purpose === "install"
          ? `${free}; GAIA needs ${gb(images + DATA_DISK_MIN_BYTES)} (its images take about ${gb(images)})`
          : `${free}; GAIA needs at least ${gb(DATA_DISK_MIN_BYTES)} for its data`,
      fix,
    };
  }
  if (freeBytes < images + DATA_DISK_RECOMMENDED_BYTES) {
    return {
      level: "warn",
      detail: `${free}; that leaves little room for GAIA's data`,
      fix,
    };
  }
  return { level: "ok", detail: free };
}

function memoryFix(host: MemoryHost): string {
  if (host.platform === "darwin") {
    return "Give Docker more memory (Docker Desktop: Settings > Resources > Memory; OrbStack: Settings > System > Memory limit), then run 'gaia up' again.";
  }
  if (host.wsl) {
    return "Raise WSL's memory limit: in %UserProfile%\\.wslconfig set '[wsl2]' 'memory=8GB', run 'wsl --shutdown' in PowerShell, then run 'gaia up' again.";
  }
  return "Run GAIA on a machine with 8 GB of RAM.";
}

export function judgeMemory(
  totalBytes: number,
  host: MemoryHost,
): ResourceVerdict {
  const total = `${gb(totalBytes)} in total for Docker`;
  if (totalBytes < MEMORY_MIN_BYTES) {
    return {
      level: "fail",
      detail: `${total}; GAIA needs at least ${gb(MEMORY_MIN_BYTES)} to start`,
      fix: memoryFix(host),
    };
  }
  if (totalBytes < MEMORY_RECOMMENDED_BYTES) {
    return {
      level: "warn",
      detail: `${total}; GAIA uses about 5.5 GB, so it may run out under load (8 GB recommended)`,
      fix: memoryFix(host),
    };
  }
  return { level: "ok", detail: total };
}

/** Available kilobytes from `df -k` output: the last line's 4th column. */
export function parseDfAvailableKb(stdout: string): number | null {
  const last = stdout
    .trim()
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .at(-1);
  if (!last) return null;
  const kb = Number(last.trim().split(/\s+/)[3]);
  return Number.isFinite(kb) && kb >= 0 ? kb : null;
}

/** Absolute path of the daemon's data root (`docker info .DockerRootDir`). */
export async function getDockerRootDir(): Promise<string> {
  const { stdout } = await execa("docker", [
    "info",
    "--format",
    "{{.DockerRootDir}}",
  ]);
  const dir = stdout.trim();
  if (!dir) throw new Error("docker info returned an empty DockerRootDir");
  return dir;
}

/**
 * Free bytes on the disk holding Docker's data root; null when that folder
 * is inside Docker's VM (Docker Desktop, OrbStack), so the host's disk is
 * not the one that fills up.
 */
export async function readDockerDiskFree(
  rootDir: string,
): Promise<number | null> {
  if (!fs.existsSync(rootDir)) return null;
  const { stdout } = await execa("df", ["-k", rootDir]);
  const kb = parseDfAvailableKb(stdout);
  if (kb === null) {
    throw new Error(`Couldn't read 'df -k ${rootDir}': ${stdout.trim()}`);
  }
  return kb * 1024;
}

/** The memory Docker can give its containers: the VM's on a Mac or WSL, the machine's on Linux. */
export async function readDockerMemoryBytes(): Promise<number> {
  const { stdout } = await execa("docker", [
    "info",
    "--format",
    "{{.MemTotal}}",
  ]);
  const bytes = Number(stdout.trim());
  if (!Number.isFinite(bytes) || bytes <= 0) {
    throw new Error(`docker info returned no MemTotal: ${stdout.trim()}`);
  }
  return bytes;
}
