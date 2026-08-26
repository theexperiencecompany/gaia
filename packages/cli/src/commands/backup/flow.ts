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
  extraFiles?: string[];
  warnings?: string[];
}

/**
 * Extra volumes beyond the critical DBs.
 *
 * - `chroma_data` (compose key) → Docker volume `gaia-selfhost_chroma_data` — vector
 *   embeddings. Re-creatable from source documents but expensive (re-embed). Backed
 *   up best-effort via `alpine tar`.
 * - `gaia-sandbox-workspace` (pinned name) → ephemeral per-user workspace. Re-creatable;
 *   keep if you care about local sandbox files.
 *
 * Other volumes (redis_data, rabbitmq_data, juicefs_cache, models_cache) are
 * transient queues/caches and intentionally NOT backed up — they repopulate on
 * restart/re-download.
 *
 * The `docker run` one-liners below use the real Docker volume names. `chroma_data`
 * is what `docker volume ls` shows as `gaia-selfhost_chroma_data` under the
 * `gaia-selfhost` project; `gaia-sandbox-workspace` is pinned via `name:` in the
 * compose file so it is literal.
 */
export const EXTRA_VOLUME_BACKUPS: ReadonlyArray<{
  volume: string;
  fileSuffix: string;
  label: string;
}> = [
  {
    volume: "gaia-selfhost_chroma_data",
    fileSuffix: "chroma_data",
    label: "Chroma",
  },
  {
    volume: "gaia-sandbox-workspace",
    fileSuffix: "sandbox-workspace",
    label: "Sandbox workspace",
  },
] as const;

async function volumeExists(volume: string): Promise<boolean> {
  try {
    const { stdout } = await execa("docker", ["volume", "inspect", volume]);
    return stdout.trim().length > 0;
  } catch {
    return false;
  }
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
  for (const v of EXTRA_VOLUME_BACKUPS) {
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
      extraFiles: EXTRA_VOLUME_BACKUPS.map((v) =>
        path.join(outDir, `${v.fileSuffix}-${date}.tar.gz`),
      ),
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

  // Extra volumes: best-effort `alpine tar` dumps. Skip silently if the volume
  // doesn't exist (fresh install or `gaia-sandbox-workspace` never created).
  // These are re-creatable (Chroma re-embeds, sandbox is ephemeral) but we still
  // snapshot them when present so a full restore is possible.
  const extraFiles: string[] = [];
  const warnings: string[] = [];
  for (const v of EXTRA_VOLUME_BACKUPS) {
    const file = path.join(outDir, `${v.fileSuffix}-${date}.tar.gz`);
    if (!(await volumeExists(v.volume))) {
      warnings.push(
        `${v.label} volume ${v.volume} not found — skipped (re-creatable)`,
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
      extraFiles.push(file);
    } catch (e) {
      warnings.push(`${v.label} backup failed: ${(e as Error).message}`);
    }
  }

  return { mongoFile, postgresFile, commands, extraFiles, warnings };
}
