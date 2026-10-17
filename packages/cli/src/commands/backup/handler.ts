/**
 * Handler for `gaia backup` — one-liner database dumps.
 * Plain-text command (no Ink) so output can be piped or pasted.
 * @module commands/backup/handler
 */

import * as path from "node:path";
import {
  VOLUME_BACKUPS,
  volumeRestoreScript,
} from "../../lib/volume-backups.js";
import { runBackup } from "./flow.js";

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
    out(
      `Volumes (${VOLUME_BACKUPS.map((v) => v.volume).join(", ")}) are backed up via`,
    );
    out(
      "  docker run --rm -v <volume>:/data -v <output>:/backups alpine tar ...",
    );
    out("  and are skipped if the volume does not exist yet.");
    out("");
    out("Run without --dry-run to execute inside the running containers,");
    out(
      "or copy-paste the commands from the directory containing infra/docker/",
    );
    return;
  }

  try {
    out("Starting GAIA backup…");
    const result = await runBackup({ outputDir: options.output });
    out(`MongoDB dump: ${result.mongoFile}`);
    out(`PostgreSQL dump: ${result.postgresFile}`);
    out(`API settings (apps/api/.env): ${result.apiEnvFile}`);
    for (const { label, file } of result.volumeFiles)
      out(`${label} archive: ${file}`);
    if (result.warnings.length) {
      for (const w of result.warnings) out(`Note: ${w}`);
    }
    out("");
    out("Backups complete. Store them off-host and access-controlled —");
    out(
      `${result.apiEnvFile} holds INSTANCE_SECRET, which decrypts the stored provider credentials.`,
    );
    out("");
    out(
      "Restore with gaia restore --from <dir>, or manually from the repo root:",
    );
    out(`  install -m 600 ${result.apiEnvFile} apps/api/.env`);
    out(
      `  cat ${result.postgresFile} | docker compose -f infra/docker/docker-compose.selfhost.yml exec -T postgres psql -U postgres -d langgraph`,
    );
    out(
      `  docker compose -f infra/docker/docker-compose.selfhost.yml exec -T mongo mongorestore --archive --gzip --drop < ${result.mongoFile}`,
    );
    for (const { volume, file } of result.volumeFiles) {
      out(
        `  docker run --rm -v ${volume}:/data -v $(dirname ${file}):/backups alpine sh -c "${volumeRestoreScript(path.basename(file))}"`,
      );
    }
  } catch (e) {
    errOut((e as Error).message);
    process.exitCode = 1;
  }
}
