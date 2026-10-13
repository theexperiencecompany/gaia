/**
 * Backup flow — dump MongoDB and PostgreSQL via Docker Compose.
 *
 * Two tiers:
 *  - `getBackupCommands` returns the exact shell commands for docs / --dry-run
 *  - `runBackup` executes them, streaming container stdout to host files
 *
 * @module commands/backup/flow
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { execa } from "execa";
import { dockerVolumeExists, isDockerRunning } from "../../lib/docker.js";
import { findRepoRoot } from "../../lib/service-starter.js";
import { VOLUME_BACKUPS, type VolumeFile } from "../../lib/volume-backups.js";

export interface BackupOptions {
  outputDir?: string;
  dryRun?: boolean;
}

export interface BackupResult {
  mongoFile: string;
  postgresFile: string;
  commands: string[];
  volumeFiles?: VolumeFile[];
  warnings?: string[];
}

/** YYYY-MM-DD for dated filenames. */
function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Exact shell one-liners shown in `--help` / docs. */
export function getBackupCommands(
  outputDir: string,
  date = todayIso(),
): string[] {
  const mongoFile = path.join(outputDir, `mongo-${date}.gz`);
  const postgresFile = path.join(outputDir, `postgres-${date}.sql`);
  const base = [
    `mkdir -p ${outputDir}`,
    `docker compose -f docker-compose.selfhost.yml exec -T mongo mongodump --archive --gzip > ${mongoFile}`,
    `docker compose -f docker-compose.selfhost.yml exec -T postgres pg_dump -U postgres -d langgraph > ${postgresFile}`,
  ];
  for (const v of VOLUME_BACKUPS) {
    const file = path.join(outputDir, `${v.fileSuffix}-${date}.tar.gz`);
    base.push(
      `docker run --rm -v ${v.volume}:/data -v ${outputDir}:/backups alpine tar czf /backups/${path.basename(file)} -C /data .`,
    );
  }
  return base;
}

/** Subset of commands for just the critical DBs (used in error hints). */
export function getCoreBackupCommands(
  outputDir: string,
  date = todayIso(),
): string[] {
  return getBackupCommands(outputDir, date).slice(0, 3);
}

function resolveDockerDir(repoPath: string): string {
  return path.join(repoPath, "infra", "docker");
}

export function resolveBackupOutputDir(
  repoPath: string,
  outputDir?: string,
): string {
  if (outputDir) return path.resolve(outputDir);
  return path.join(repoPath, "backups");
}

export async function runBackup(
  options: BackupOptions = {},
): Promise<BackupResult> {
  const repoPath = findRepoRoot();
  if (!repoPath) {
    throw new Error(
      "Could not find GAIA repository. Run from within a cloned gaia repo or set the recorded install path.",
    );
  }

  const dockerDir = resolveDockerDir(repoPath);
  const composeFile = path.join(dockerDir, "docker-compose.selfhost.yml");
  if (!fs.existsSync(composeFile)) {
    throw new Error(`Compose file not found: ${composeFile}`);
  }

  const outDir = resolveBackupOutputDir(repoPath, options.outputDir);
  const date = todayIso();
  const mongoFile = path.join(outDir, `mongo-${date}.gz`);
  const postgresFile = path.join(outDir, `postgres-${date}.sql`);
  const commands = getBackupCommands(outDir, date);

  if (options.dryRun) {
    return {
      mongoFile,
      postgresFile,
      commands,
      volumeFiles: VOLUME_BACKUPS.map((v) => ({
        volume: v.volume,
        label: v.label,
        file: path.join(outDir, `${v.fileSuffix}-${date}.tar.gz`),
      })),
    };
  }

  const dockerRunning = await isDockerRunning();
  if (!dockerRunning) {
    throw new Error(
      [
        "Docker daemon is not running — cannot run container dumps.",
        "Start Docker and retry, or run the manual commands:",
        ...commands.map((c) => `  ${c}`),
      ].join("\n"),
    );
  }

  await fs.promises.mkdir(outDir, { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(outDir, 0o700);
  } catch {
    // Best-effort — the directory is already created; a chmod failure
    // (e.g. on a read-only mount) must not abort the backup.
  }

  // Mongo dump: stream stdout to host file (0600 — dump contains
  // instance_secret and all provider ciphertext).
  try {
    const mongoProc = execa(
      "docker",
      [
        "compose",
        "-f",
        "docker-compose.selfhost.yml",
        "exec",
        "-T",
        "mongo",
        "mongodump",
        "--archive",
        "--gzip",
      ],
      { cwd: dockerDir, stdout: "pipe", stderr: "pipe" },
    );
    if (!mongoProc.stdout) throw new Error("Failed to pipe mongo dump");
    const out = fs.createWriteStream(mongoFile, { mode: 0o600 });
    mongoProc.stdout.pipe(out);
    await mongoProc;
    await new Promise<void>((resolve, reject) => {
      out.on("finish", resolve);
      out.on("error", reject);
    });
    try {
      fs.chmodSync(mongoFile, 0o600);
    } catch {
      // See above — best-effort hardening if chmod is unavailable.
    }
  } catch (e) {
    try {
      fs.unlinkSync(mongoFile);
    } catch {
      // No partial file to clean up, or FS is already gone.
    }
    throw new Error(
      `MongoDB backup failed: ${(e as Error).message}\nManual command: ${commands[1]}`,
    );
  }

  // Postgres dump (same 0600 hardening as Mongo).
  try {
    const pgProc = execa(
      "docker",
      [
        "compose",
        "-f",
        "docker-compose.selfhost.yml",
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        "langgraph",
      ],
      { cwd: dockerDir, stdout: "pipe", stderr: "pipe" },
    );
    if (!pgProc.stdout) throw new Error("Failed to pipe postgres dump");
    const out = fs.createWriteStream(postgresFile, { mode: 0o600 });
    pgProc.stdout.pipe(out);
    await pgProc;
    await new Promise<void>((resolve, reject) => {
      out.on("finish", resolve);
      out.on("error", reject);
    });
    try {
      fs.chmodSync(postgresFile, 0o600);
    } catch {
      // Best-effort.
    }
  } catch (e) {
    try {
      fs.unlinkSync(postgresFile);
    } catch {
      // No partial file.
    }
    throw new Error(
      `PostgreSQL backup failed: ${(e as Error).message}\nManual command: ${commands[2]}`,
    );
  }

  // `alpine tar` archives. A missing volume is a fresh install with nothing
  // stored yet; a failed archive of user data fails the backup.
  const volumeFiles: VolumeFile[] = [];
  const warnings: string[] = [];
  for (const v of VOLUME_BACKUPS) {
    const file = path.join(outDir, `${v.fileSuffix}-${date}.tar.gz`);
    if (!(await dockerVolumeExists(v.volume))) {
      warnings.push(
        `${v.label} volume ${v.volume} not found — nothing to back up`,
      );
      continue;
    }
    try {
      await execa(
        "docker",
        [
          "run",
          "--rm",
          "-v",
          `${v.volume}:/data`,
          "-v",
          `${outDir}:/backups`,
          "alpine",
          "tar",
          "czf",
          `/backups/${path.basename(file)}`,
          "-C",
          "/data",
          ".",
        ],
        { cwd: dockerDir },
      );
      try {
        fs.chmodSync(file, 0o600);
      } catch {
        // Best-effort hardening.
      }
      volumeFiles.push({ volume: v.volume, label: v.label, file });
    } catch (e) {
      try {
        fs.unlinkSync(file);
      } catch {
        // No partial file or already cleaned.
      }
      const message = `${v.label} backup failed: ${(e as Error).message}`;
      if (v.userData) throw new Error(message);
      warnings.push(message);
    }
  }

  return { mongoFile, postgresFile, commands, volumeFiles, warnings };
}
