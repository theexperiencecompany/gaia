/**
 * Restore flow — put back apps/api/.env (the key the stored credentials are
 * encrypted under), then re-load the MongoDB and PostgreSQL dumps and volumes.
 *
 * Mirrors `backup/flow.ts`: validates files, runs the container commands, and
 * surfaces manual fallbacks when Docker is unreachable or a file is missing.
 *
 * @module commands/restore/flow
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { execa } from "execa";
import { backupFileSet, latestBackupStamp } from "../../lib/backup-files.js";
import {
  describeDockerProblem,
  getDockerAccess,
} from "../../lib/docker-access.js";
import {
  copyEnvFileOwnerOnly,
  readDockerComposePortOverrides,
} from "../../lib/env-writer.js";
import {
  apiEnvPath,
  findInstallRoot,
  startServices,
} from "../../lib/service-starter.js";
import {
  type VolumeFile,
  volumeRestoreScript,
} from "../../lib/volume-backups.js";

export interface RestoreOptions {
  mongoFile?: string;
  postgresFile?: string;
  /** The backup's apps/api/.env; its INSTANCE_SECRET decrypts the Mongo dump's credentials. */
  apiEnvFile?: string;
  fromDir?: string;
  dryRun?: boolean;
}

export interface ResolvedRestoreFiles {
  mongoFile?: string;
  postgresFile?: string;
  apiEnvFile?: string;
  volumeFiles: VolumeFile[];
}

export function resolveRestoreFiles(
  options: RestoreOptions,
): ResolvedRestoreFiles {
  if (options.fromDir) {
    const dir = path.resolve(options.fromDir);
    const stamp = latestBackupStamp(dir);
    if (!stamp) return { volumeFiles: [] };
    // Every file of the newest run, and only that run: mixing runs would
    // pair a dump with another run's files or INSTANCE_SECRET.
    const files = backupFileSet(dir, stamp);
    const present = (file: string): string | undefined =>
      fs.existsSync(file) ? file : undefined;
    return {
      mongoFile: options.mongoFile ?? present(files.mongoFile),
      postgresFile: options.postgresFile ?? present(files.postgresFile),
      apiEnvFile: options.apiEnvFile ?? present(files.apiEnvFile),
      volumeFiles: files.volumeFiles.filter((v) => fs.existsSync(v.file)),
    };
  }
  return {
    mongoFile: options.mongoFile,
    postgresFile: options.postgresFile,
    apiEnvFile: options.apiEnvFile,
    volumeFiles: [],
  };
}

/** What a restore of these files cannot guarantee, said before it runs. */
export function restoreWarnings(files: ResolvedRestoreFiles): string[] {
  if (!files.mongoFile || files.apiEnvFile) return [];
  return [
    "Restoring MongoDB without the backup's apps/api/.env: the stored provider credentials decrypt only under the INSTANCE_SECRET they were saved with. " +
      "If this install's apps/api/.env is not the one the dump was taken with, they will not decrypt. Pass the backup's api-env-<stamp>.env with --env, or restore with --from <dir>.",
  ];
}

export function getRestoreCommands(files: ResolvedRestoreFiles): string[] {
  const { mongoFile, postgresFile, apiEnvFile, volumeFiles } = files;
  const cmds: string[] = [];
  if (apiEnvFile) {
    cmds.push(`install -m 600 ${apiEnvFile} ../../apps/api/.env`);
  }
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
  options: RestoreOptions,
  onStatus: (message: string) => void,
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
  const { mongoFile, postgresFile, apiEnvFile, volumeFiles } = resolved;
  const commands = getRestoreCommands(resolved);

  if (!mongoFile && !postgresFile && !apiEnvFile && volumeFiles.length === 0) {
    throw new Error(
      [
        "No backup files specified.",
        "Use --mongo <file> --postgres <file> or --from <backup-dir> containing mongo-*.gz and postgres-*.sql.",
        "Example: gaia restore --from backups",
        "Example: gaia restore --mongo backups/mongo-2026-08-27T09-30-00Z.gz --postgres backups/postgres-2026-08-27T09-30-00Z.sql",
      ].join("\n"),
    );
  }

  if (apiEnvFile && !fs.existsSync(apiEnvFile))
    throw new Error(`apps/api/.env backup not found: ${apiEnvFile}`);
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

  const access = await getDockerAccess();
  if (access !== "ready") {
    const problem = await describeDockerProblem(access);
    throw new Error(
      [
        `${problem.summary}, so nothing can be restored.`,
        problem.fix,
        "Or run the restore commands yourself:",
        ...commands.map((c) => `  ${c}`),
      ].join("\n"),
    );
  }

  if (apiEnvFile) restoreApiEnv(apiEnvFile, repoPath);

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

  // The `gaia start` path: the same compose files (the code sandbox included),
  // and compose recreates every container whose env files changed.
  onStatus(
    "Restarting services so they load the restored data and settings...",
  );
  await startServices(
    repoPath,
    "selfhost",
    onStatus,
    readDockerComposePortOverrides(repoPath),
  );

  return { ...resolved, commands };
}

/**
 * Put the backup's apps/api/.env back (the replaced file is kept as .env.bak):
 * the restored dump's credentials decrypt only under its INSTANCE_SECRET.
 */
export function restoreApiEnv(apiEnvFile: string, repoPath: string): void {
  copyEnvFileOwnerOnly(apiEnvFile, apiEnvPath(repoPath));
}
