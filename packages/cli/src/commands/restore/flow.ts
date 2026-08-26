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
import { findRepoRoot } from "../../lib/service-starter.js";

export interface RestoreOptions {
  mongoFile?: string;
  postgresFile?: string;
  fromDir?: string;
  dryRun?: boolean;
}

export function resolveRestoreFiles(options: RestoreOptions): {
  mongoFile?: string;
  postgresFile?: string;
} {
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
    };
  }
  return { mongoFile: options.mongoFile, postgresFile: options.postgresFile };
}

export function getRestoreCommands(
  mongoFile?: string,
  postgresFile?: string,
): string[] {
  const cmds: string[] = [];
  if (mongoFile) {
    cmds.push(
      `docker compose -f docker-compose.selfhost.yml exec -T mongo mongorestore --archive --gzip --drop < ${mongoFile}`,
    );
  }
  if (postgresFile) {
    cmds.push(
      `docker compose -f docker-compose.selfhost.yml exec postgres psql -U postgres -d langgraph -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'`,
    );
    cmds.push(
      `cat ${postgresFile} | docker compose -f docker-compose.selfhost.yml exec -T postgres psql -U postgres -d langgraph`,
    );
  }
  return cmds;
}

export async function runRestore(
  options: RestoreOptions = {},
): Promise<{ mongoFile?: string; postgresFile?: string; commands: string[] }> {
  const repoPath = findRepoRoot();
  if (!repoPath) {
    throw new Error(
      "Could not find GAIA repository. Run from within a cloned gaia repo.",
    );
  }
  const dockerDir = path.join(repoPath, "infra", "docker");
  const composeFile = path.join(dockerDir, "docker-compose.selfhost.yml");
  if (!fs.existsSync(composeFile))
    throw new Error(`Compose file not found: ${composeFile}`);

  const { mongoFile, postgresFile } = resolveRestoreFiles(options);
  const commands = getRestoreCommands(mongoFile, postgresFile);

  if (!mongoFile && !postgresFile) {
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

  if (options.dryRun) {
    return { mongoFile, postgresFile, commands };
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

  return { mongoFile, postgresFile, commands };
}
