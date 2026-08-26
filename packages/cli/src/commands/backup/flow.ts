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
import { isDockerRunning } from "../../lib/docker.js";
import { findRepoRoot } from "../../lib/service-starter.js";

export interface BackupOptions {
  outputDir?: string;
  dryRun?: boolean;
}

export interface BackupResult {
  mongoFile: string;
  postgresFile: string;
  commands: string[];
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
  return [
    `mkdir -p ${outputDir}`,
    `docker compose -f docker-compose.selfhost.yml exec -T mongo mongodump --archive --gzip > ${mongoFile}`,
    `docker compose -f docker-compose.selfhost.yml exec -T postgres pg_dump -U postgres -d langgraph > ${postgresFile}`,
  ];
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
    return { mongoFile, postgresFile, commands };
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

  await fs.promises.mkdir(outDir, { recursive: true });

  // Mongo dump: stream stdout to host file.
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
    const out = fs.createWriteStream(mongoFile);
    mongoProc.stdout.pipe(out);
    await mongoProc;
    await new Promise<void>((resolve, reject) => {
      out.on("finish", resolve);
      out.on("error", reject);
    });
  } catch (e) {
    throw new Error(
      `MongoDB backup failed: ${(e as Error).message}\nManual command: ${commands[1]}`,
    );
  }

  // Postgres dump
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
    const out = fs.createWriteStream(postgresFile);
    pgProc.stdout.pipe(out);
    await pgProc;
    await new Promise<void>((resolve, reject) => {
      out.on("finish", resolve);
      out.on("error", reject);
    });
  } catch (e) {
    throw new Error(
      `PostgreSQL backup failed: ${(e as Error).message}\nManual command: ${commands[2]}`,
    );
  }

  return { mongoFile, postgresFile, commands };
}
