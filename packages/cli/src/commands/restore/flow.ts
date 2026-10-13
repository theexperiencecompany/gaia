/**
 * Restore flow — re-load MongoDB and PostgreSQL dumps into the self-host stack.
 *
 * Mirrors `backup/flow.ts`: validates files, runs the container commands, and
 * surfaces manual fallbacks when Docker is unreachable or a file is missing.
 *
 * @module commands/restore/flow
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { execa } from "execa";
import { isDockerRunning } from "../../lib/docker.js";
import { findInstallRoot } from "../../lib/service-starter.js";
import {
  VOLUME_BACKUPS,
  type VolumeFile,
  volumeRestoreScript,
} from "../../lib/volume-backups.js";

export interface RestoreOptions {
  mongoFile?: string;
  postgresFile?: string;
  fromDir?: string;
  dryRun?: boolean;
}

export interface ResolvedRestoreFiles {
  mongoFile?: string;
  postgresFile?: string;
  volumeFiles: VolumeFile[];
}

export function resolveRestoreFiles(
  options: RestoreOptions,
): ResolvedRestoreFiles {
  if (options.fromDir) {
    const dir = path.resolve(options.fromDir);
    // Pick most recent matching file when a directory is given.
    const pickLatest = (prefix: string, suffix: string): string | undefined => {
      if (!fs.existsSync(dir)) return undefined;
      const candidates = fs
        .readdirSync(dir)
        .filter((f) => f.startsWith(prefix) && f.endsWith(suffix))
        .map((f) => path.join(dir, f))
        .sort();
      return candidates.at(-1);
    };
    return {
      mongoFile: options.mongoFile ?? pickLatest("mongo-", ".gz"),
      postgresFile: options.postgresFile ?? pickLatest("postgres-", ".sql"),
      volumeFiles: VOLUME_BACKUPS.flatMap((v) => {
        const file = pickLatest(`${v.fileSuffix}-`, ".tar.gz");
        return file ? [{ volume: v.volume, label: v.label, file }] : [];
      }),
    };
  }
  return {
    mongoFile: options.mongoFile,
    postgresFile: options.postgresFile,
    volumeFiles: [],
  };
}

export function getRestoreCommands(files: ResolvedRestoreFiles): string[] {
  const { mongoFile, postgresFile, volumeFiles } = files;
  const cmds: string[] = [];
  if (mongoFile) {
    cmds.push(
      `docker compose -f docker-compose.selfhost.yml exec -T mongo mongorestore --archive --gzip --drop < ${mongoFile}`,
    );
  }
  if (postgresFile) {
    cmds.push(
      `docker compose -f docker-compose.selfhost.yml exec -T postgres psql -U postgres -d langgraph -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`,
    );
    cmds.push(
      `cat ${postgresFile} | docker compose -f docker-compose.selfhost.yml exec -T postgres psql -U postgres -d langgraph`,
    );
  }
  for (const { volume, file } of volumeFiles) {
    cmds.push(
      `docker run --rm -v ${volume}:/data -v ${path.dirname(file)}:/backups alpine sh -c "${volumeRestoreScript(path.basename(file))}"`,
    );
  }
  return cmds;
}

export async function runRestore(
  options: RestoreOptions = {},
): Promise<ResolvedRestoreFiles & { commands: string[] }> {
  const repoPath = findInstallRoot();
  if (!repoPath) {
    throw new Error(
      "Could not find GAIA repository. Run from within a cloned gaia repo.",
    );
  }
  const dockerDir = path.join(repoPath, "infra", "docker");
  const composeFile = path.join(dockerDir, "docker-compose.selfhost.yml");
  if (!fs.existsSync(composeFile))
    throw new Error(`Compose file not found: ${composeFile}`);

  const resolved = resolveRestoreFiles(options);
  const { mongoFile, postgresFile, volumeFiles } = resolved;
  const commands = getRestoreCommands(resolved);

  if (!mongoFile && !postgresFile && volumeFiles.length === 0) {
    throw new Error(
      [
        "No backup files specified.",
        "Use --mongo <file> --postgres <file> or --from <backup-dir> containing mongo-*.gz and postgres-*.sql.",
        "Example: gaia restore --from backups",
        "Example: gaia restore --mongo backups/mongo-2026-08-27.gz --postgres backups/postgres-2026-08-27.sql",
      ].join("\n"),
    );
  }

  if (mongoFile && !fs.existsSync(mongoFile))
    throw new Error(`Mongo backup not found: ${mongoFile}`);
  if (postgresFile && !fs.existsSync(postgresFile))
    throw new Error(`Postgres backup not found: ${postgresFile}`);
  for (const { label, file } of volumeFiles) {
    if (!fs.existsSync(file))
      throw new Error(`${label} backup not found: ${file}`);
  }

  if (options.dryRun) {
    return { ...resolved, commands };
  }

  const dockerRunning = await isDockerRunning();
  if (!dockerRunning) {
    throw new Error(
      [
        "Docker daemon is not running — cannot restore.",
        "Manual commands:",
        ...commands.map((c) => `  ${c}`),
      ].join("\n"),
    );
  }

  if (mongoFile) {
    try {
      const proc = execa(
        "docker",
        [
          "compose",
          "-f",
          "docker-compose.selfhost.yml",
          "exec",
          "-T",
          "mongo",
          "mongorestore",
          "--archive",
          "--gzip",
          "--drop",
        ],
        { cwd: dockerDir, stdin: "pipe", stderr: "pipe" },
      );
      const read = fs.createReadStream(mongoFile);
      if (!proc.stdin) throw new Error("Failed to pipe mongo restore stdin");
      read.pipe(proc.stdin);
      await proc;
    } catch (e) {
      throw new Error(`MongoDB restore failed: ${(e as Error).message}`);
    }
  }

  if (postgresFile) {
    // Start from empty schema so restore doesn't collide with existing tables.
    try {
      await execa(
        "docker",
        [
          "compose",
          "-f",
          "docker-compose.selfhost.yml",
          "exec",
          "-T",
          "postgres",
          "psql",
          "-U",
          "postgres",
          "-d",
          "langgraph",
          "-c",
          "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ],
        { cwd: dockerDir },
      );
    } catch (e) {
      throw new Error(`Postgres schema reset failed: ${(e as Error).message}`);
    }

    try {
      const proc = execa(
        "docker",
        [
          "compose",
          "-f",
          "docker-compose.selfhost.yml",
          "exec",
          "-T",
          "postgres",
          "psql",
          "-U",
          "postgres",
          "-d",
          "langgraph",
        ],
        { cwd: dockerDir, stdin: "pipe", stderr: "pipe" },
      );
      const read = fs.createReadStream(postgresFile);
      if (!proc.stdin) throw new Error("Failed to pipe postgres restore stdin");
      read.pipe(proc.stdin);
      await proc;
    } catch (e) {
      throw new Error(`PostgreSQL restore failed: ${(e as Error).message}`);
    }
  }

  // Volumes: alpine tar restores mirroring backup (lib/volume-backups.ts).
  // A missing volume is created implicitly by `docker run -v`.
  for (const { file, volume, label } of volumeFiles) {
    try {
      await execa(
        "docker",
        [
          "run",
          "--rm",
          "-v",
          `${volume}:/data`,
          "-v",
          `${path.dirname(file)}:/backups`,
          "alpine",
          "sh",
          "-c",
          volumeRestoreScript(path.basename(file)),
        ],
        { cwd: dockerDir },
      );
    } catch (e) {
      throw new Error(`${label} restore failed: ${(e as Error).message}`);
    }
  }

  return { ...resolved, commands };
}
