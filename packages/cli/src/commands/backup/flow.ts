/**
 * Backup flow — dump MongoDB and PostgreSQL via Docker Compose, archive the
 * storage volumes, and copy apps/api/.env: it holds INSTANCE_SECRET, the key
 * the Mongo dump's stored credentials are encrypted under.
 *
 * Two tiers:
 *  - `getBackupCommands` returns the exact shell commands for docs / --dry-run
 *  - `runBackup` executes them, streaming container stdout to host files
 *
 * @module commands/backup/flow
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { ExecaError, execa } from "execa";
import {
  type BackupFileSet,
  backupFileSet,
  backupStamp,
  partialPath,
  volumeBackupFile,
} from "../../lib/backup-files.js";
import {
  COMPOSE_PROJECT_BY_MODE,
  dockerVolumeExists,
  getComposeProjectContainers,
} from "../../lib/docker.js";
import {
  describeDockerProblem,
  getDockerAccess,
} from "../../lib/docker-access.js";
import { copyEnvFileOwnerOnly } from "../../lib/env-writer.js";
import { homeRelative } from "../../lib/paths.js";
import { apiEnvPath, findInstallRoot } from "../../lib/service-starter.js";
import { VOLUME_BACKUPS, type VolumeFile } from "../../lib/volume-backups.js";

/** The compose services whose databases a backup dumps. */
const DUMPED_SERVICES = ["mongo", "postgres"];

export interface BackupOptions {
  outputDir?: string;
  dryRun?: boolean;
  /** Hears the id of each BACKUP_PARTS entry as the backup starts on it. */
  onPart?: (id: string) => void;
}

/** What a backup saves, in the order it saves them: the lines under its step. */
export const BACKUP_PARTS: readonly { id: string; label: string }[] = [
  { id: "settings", label: "Settings" },
  { id: "mongo", label: "MongoDB" },
  { id: "postgres", label: "PostgreSQL" },
  ...VOLUME_BACKUPS.map((v) => ({ id: v.volume, label: v.label })),
];

export interface BackupResult extends BackupFileSet {
  commands: string[];
  warnings: string[];
}

/** Exact shell one-liners shown in `--help` / docs, run from infra/docker/. */
export function getBackupCommands(
  outputDir: string,
  stamp = backupStamp(),
): string[] {
  const files = backupFileSet(outputDir, stamp);
  return [
    `mkdir -p ${outputDir}`,
    `docker compose -f docker-compose.selfhost.yml exec -T mongo mongodump --archive --gzip > ${files.mongoFile}`,
    `docker compose -f docker-compose.selfhost.yml exec -T postgres pg_dump -U postgres -d langgraph > ${files.postgresFile}`,
    `install -m 600 ../../apps/api/.env ${files.apiEnvFile}`,
    ...files.volumeFiles.map(
      ({ volume, file }) =>
        `docker run --rm -v ${volume}:/data -v ${outputDir}:/backups alpine tar czf /backups/${path.basename(file)} -C /data .`,
    ),
  ];
}

/** Whether both databases a backup dumps are running; a dump runs inside their containers. */
async function databasesRunning(): Promise<boolean> {
  const containers = await getComposeProjectContainers(
    COMPOSE_PROJECT_BY_MODE.selfhost,
  );
  return DUMPED_SERVICES.every((service) =>
    containers.some((c) => c.service === service && c.state === "running"),
  );
}

/** What a failed docker command said, in its own last words, not the command line it ran. */
function commandFailure(error: unknown): string {
  const stderr =
    error instanceof ExecaError ? String(error.stderr ?? "").trim() : "";
  return stderr.split("\n").at(-1) || (error as Error).message;
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
  const repoPath = findInstallRoot();
  if (!repoPath) {
    throw new Error(
      "GAIA isn't installed here, so there is nothing to back up.\nInstall it with 'gaia up'.",
    );
  }

  const dockerDir = resolveDockerDir(repoPath);
  const composeFile = path.join(dockerDir, "docker-compose.selfhost.yml");
  if (!fs.existsSync(composeFile)) {
    throw new Error(
      `${homeRelative(repoPath)} is missing its setup files, so it can't be backed up.\nRun 'gaia up' to restore them.`,
    );
  }

  const outDir = resolveBackupOutputDir(repoPath, options.outputDir);
  const stamp = backupStamp();
  const files = backupFileSet(outDir, stamp);
  const commands = getBackupCommands(outDir, stamp);

  if (options.dryRun) {
    return { ...files, commands, warnings: [] };
  }

  const access = await getDockerAccess();
  if (access !== "ready") {
    const problem = await describeDockerProblem(access);
    throw new Error(
      `${problem.summary}, so the databases can't be backed up.\n${problem.fix}`,
    );
  }
  if (!(await databasesRunning())) {
    throw new Error(
      "GAIA isn't running, so its databases can't be backed up.\nStart it with 'gaia start', then try again.",
    );
  }

  await fs.promises.mkdir(outDir, { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(outDir, 0o700);
  } catch {
    // Best-effort — the directory is already created; a chmod failure
    // (e.g. on a read-only mount) must not abort the backup.
  }

  // Every file is written under its partial name and renamed only once the
  // whole run succeeded, so a failed run never shadows the last good one.
  const allFiles = [
    files.mongoFile,
    files.postgresFile,
    files.apiEnvFile,
    ...files.volumeFiles.map((v) => v.file),
  ];
  let written: { volumeFiles: VolumeFile[]; warnings: string[] };
  try {
    written = await writeBackupFiles(
      repoPath,
      dockerDir,
      outDir,
      stamp,
      options.onPart,
    );
  } catch (e) {
    for (const file of allFiles) fs.rmSync(partialPath(file), { force: true });
    throw e;
  }
  for (const file of [
    files.mongoFile,
    files.postgresFile,
    files.apiEnvFile,
    ...written.volumeFiles.map((v) => v.file),
  ]) {
    fs.renameSync(partialPath(file), file);
  }

  return { ...files, ...written, commands };
}

/** Write the run's files under their partial names; returns the volumes archived. */
async function writeBackupFiles(
  repoPath: string,
  dockerDir: string,
  outDir: string,
  stamp: string,
  onPart: (id: string) => void = () => undefined,
): Promise<{ volumeFiles: VolumeFile[]; warnings: string[] }> {
  const files = backupFileSet(outDir, stamp);
  onPart("settings");
  backupApiEnv(repoPath, partialPath(files.apiEnvFile));

  onPart("mongo");
  try {
    await streamCommandToFile(
      "docker",
      composeExecArgs("mongo", ["mongodump", "--archive", "--gzip"]),
      dockerDir,
      partialPath(files.mongoFile),
    );
  } catch (e) {
    throw new Error(
      `MongoDB wasn't backed up: ${commandFailure(e)}\n'gaia status' shows whether it is running.`,
    );
  }
  onPart("postgres");
  try {
    await streamCommandToFile(
      "docker",
      composeExecArgs("postgres", [
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        "langgraph",
      ]),
      dockerDir,
      partialPath(files.postgresFile),
    );
  } catch (e) {
    throw new Error(
      `PostgreSQL wasn't backed up: ${commandFailure(e)}\n'gaia status' shows whether it is running.`,
    );
  }

  // `alpine tar` archives. A missing volume is a fresh install with nothing
  // stored yet; a failed archive of user data fails the backup.
  const volumeFiles: VolumeFile[] = [];
  const warnings: string[] = [];
  for (const v of VOLUME_BACKUPS) {
    const target = volumeBackupFile(outDir, stamp, v);
    const partial = partialPath(target.file);
    onPart(v.volume);
    if (!(await dockerVolumeExists(v.volume))) continue;
    try {
      await execa(
        "docker",
        [
          "run",
          "--rm",
          "-v",
          `${v.volume}:/data`,
          "-v",
          `${path.dirname(partial)}:/backups`,
          "alpine",
          "tar",
          "czf",
          `/backups/${path.basename(partial)}`,
          "-C",
          "/data",
          ".",
        ],
        { cwd: dockerDir },
      );
      try {
        fs.chmodSync(partial, 0o600);
      } catch {
        // Best-effort hardening.
      }
      volumeFiles.push(target);
    } catch (e) {
      fs.rmSync(partial, { force: true });
      const message = `${v.label} wasn't backed up: ${(e as Error).message}`;
      if (v.userData) throw new Error(message);
      warnings.push(message);
    }
  }
  return { volumeFiles, warnings };
}

/**
 * Copy the install's apps/api/.env into the backup. A backup without it would
 * restore credentials no key can decrypt, so a missing file fails the backup.
 */
export function backupApiEnv(repoPath: string, apiEnvFile: string): void {
  const source = apiEnvPath(repoPath);
  if (!fs.existsSync(source)) {
    throw new Error(
      `${source} not found — it holds INSTANCE_SECRET, without which the backup's stored credentials cannot be decrypted. Run gaia up to configure this install.`,
    );
  }
  copyEnvFileOwnerOnly(source, apiEnvFile);
}

function composeExecArgs(service: string, command: string[]): string[] {
  return [
    "compose",
    "-f",
    "docker-compose.selfhost.yml",
    "exec",
    "-T",
    service,
    ...command,
  ];
}

/** Run a command and write its stdout to an owner-only file; a failed run removes the file. */
export async function streamCommandToFile(
  command: string,
  args: string[],
  cwd: string,
  file: string,
): Promise<void> {
  // The dump holds every stored credential's ciphertext. Created owner-only
  // (never reusing an existing file) because execa keeps the mode it finds.
  fs.writeFileSync(file, "", { mode: 0o600, flag: "wx" });
  try {
    await execa(command, args, {
      cwd,
      stdout: { file },
      buffer: { stdout: false },
    });
  } catch (e) {
    fs.rmSync(file, { force: true });
    throw e;
  }
}
