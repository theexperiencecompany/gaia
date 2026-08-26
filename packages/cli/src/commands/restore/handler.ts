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
    const { mongoFile, postgresFile, chromaFile, sandboxFile } =
      resolveRestoreFiles({
        mongoFile: options.mongo,
        postgresFile: options.postgres,
        fromDir: options.from,
        dryRun: true,
      });
    const cmds = getRestoreCommands(
      mongoFile,
      postgresFile,
      chromaFile,
      sandboxFile,
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
    if (result.mongoFile) out(`Restored MongoDB from ${result.mongoFile}`);
    if (result.postgresFile)
      out(`Restored PostgreSQL from ${result.postgresFile}`);
    if (result.chromaFile) out(`Restored Chroma from ${result.chromaFile}`);
    if (result.sandboxFile)
      out(`Restored sandbox workspace from ${result.sandboxFile}`);
    out(
      "Restore complete. Restart app containers so sessions re-issue: docker compose -f infra/docker/docker-compose.selfhost.yml restart gaia-backend arq_worker",
    );
  } catch (e) {
    errOut((e as Error).message);
    process.exitCode = 1;
  }
}
