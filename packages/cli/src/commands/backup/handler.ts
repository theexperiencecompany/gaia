/**
 * Handler for `gaia backup` — one-liner database dumps.
 * Plain-text command (no Ink) so output can be piped or pasted.
 * @module commands/backup/handler
 */

import { getBackupCommands, runBackup } from "./flow.js";

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

function errOut(line = ""): void {
  process.stderr.write(`${line}\n`);
}

export async function runBackupCommand(
  options: { output?: string; dryRun?: boolean } = {},
): Promise<void> {
  if (options.dryRun) {
    const result = await runBackup({ outputDir: options.output, dryRun: true });
    out("Backup commands (dry run — not executed):");
    for (const cmd of result.commands) out(`  ${cmd}`);
    out("");
    out("Run without --dry-run to execute inside the running containers,");
    out(
      "or copy-paste the commands from the directory containing infra/docker/",
    );
    return;
  }

  try {
    out("Starting GAIA backup...");
    const result = await runBackup({ outputDir: options.output });
    out(`MongoDB dump: ${result.mongoFile}`);
    out(`PostgreSQL dump: ${result.postgresFile}`);
    out("");
    out("Backups complete. Store them off-host and access-controlled —");
    out(
      "the Mongo archive contains the instance secret and decrypts provider credentials.",
    );
    out("");
    out("Restore with:");
    out(
      `  cat ${result.postgresFile} | docker compose -f infra/docker/docker-compose.selfhost.yml exec -T postgres psql -U postgres -d langgraph`,
    );
    out(
      `  docker compose -f infra/docker/docker-compose.selfhost.yml exec -T mongo mongorestore --archive --gzip --drop < ${result.mongoFile}`,
    );
  } catch (e) {
    errOut((e as Error).message);
    process.exitCode = 1;
  }
}

/** Help text for `gaia backup --help` — also used when Docker is down. */
export function printBackupHelp(): void {
  const sample = getBackupCommands("backups");
  out("Back up GAIA databases (MongoDB + PostgreSQL) via Docker Compose.");
  out("");
  out("Usage: gaia backup [--output <dir>] [--dry-run]");
  out("");
  out("Manual one-liner (from infra/docker/):");
  for (const cmd of sample) out(`  ${cmd}`);
  out("");
  out("Restore (from infra/docker/):");
  out(
    "  docker compose -f docker-compose.selfhost.yml exec -T mongo mongorestore --archive --gzip --drop < backups/mongo-YYYY-MM-DD.gz",
  );
  out(
    "  docker compose -f docker-compose.selfhost.yml exec postgres psql -U postgres -d langgraph -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'",
  );
  out(
    "  cat backups/postgres-YYYY-MM-DD.sql | docker compose -f docker-compose.selfhost.yml exec -T postgres psql -U postgres -d langgraph",
  );
}
