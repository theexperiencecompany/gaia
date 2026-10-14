/**
 * Handler for `gaia restore` — reload backups into the self-host stack.
 * Plain-text command (no Ink).
 * @module commands/restore/handler
 */

import { getRestoreCommands, resolveRestoreFiles, runRestore } from "./flow.js";

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}
function errOut(line = ""): void {
  process.stderr.write(`${line}\n`);
}

export async function runRestoreCommand(
  options: {
    mongo?: string;
    postgres?: string;
    from?: string;
    dryRun?: boolean;
  } = {},
): Promise<void> {
  if (options.dryRun) {
    const cmds = getRestoreCommands(
      resolveRestoreFiles({
        mongoFile: options.mongo,
        postgresFile: options.postgres,
        fromDir: options.from,
        dryRun: true,
      }),
    );
    if (cmds.length === 0) {
      out(
        "No backup files resolved. Use --from <dir> or --mongo/--postgres <file>.",
      );
      return;
    }
    out("Restore commands (dry run — not executed):");
    for (const c of cmds) out(`  ${c}`);
    return;
  }

  try {
    out("Starting GAIA restore...");
    const result = await runRestore({
      mongoFile: options.mongo,
      postgresFile: options.postgres,
      fromDir: options.from,
    });
    if (result.apiEnvFile)
      out(`Restored apps/api/.env from ${result.apiEnvFile}`);
    if (result.mongoFile) out(`Restored MongoDB from ${result.mongoFile}`);
    if (result.postgresFile)
      out(`Restored PostgreSQL from ${result.postgresFile}`);
    for (const { label, file } of result.volumeFiles)
      out(`Restored ${label} from ${file}`);
    out(
      "Restore complete. Recreate the app containers so they load the restored settings: docker compose -f infra/docker/docker-compose.selfhost.yml up -d --force-recreate gaia-backend arq_worker",
    );
  } catch (e) {
    errOut((e as Error).message);
    process.exitCode = 1;
  }
}
