/**
 * Handler for `gaia restore` — reload backups into the self-host stack.
 * Plain-text command (no Ink).
 * @module commands/restore/handler
 */

import { printError } from "../../lib/print-error.js";
import { MARK } from "../../ui/constants.js";
import {
  getRestoreCommands,
  type RestoreOptions,
  resolveRestoreFiles,
  restoreWarnings,
  runRestore,
} from "./flow.js";

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
    env?: string;
    from?: string;
    dryRun?: boolean;
  } = {},
): Promise<void> {
  const restoreOptions: RestoreOptions = {
    mongoFile: options.mongo,
    postgresFile: options.postgres,
    apiEnvFile: options.env,
    fromDir: options.from,
  };
  const resolved = resolveRestoreFiles(restoreOptions);
  for (const warning of restoreWarnings(resolved))
    errOut(`${MARK.warn} ${warning}`);

  if (options.dryRun) {
    const cmds = getRestoreCommands(resolved);
    if (cmds.length === 0) {
      out(
        "No backup files resolved. Use --from <dir> or --mongo/--postgres/--env <file>.",
      );
      return;
    }
    out("Restore commands (dry run — not executed):");
    for (const c of cmds) out(`  ${c}`);
    return;
  }

  try {
    out("Starting GAIA restore…");
    const result = await runRestore(restoreOptions, (message) =>
      out(`  ${message}`),
    );
    if (result.apiEnvFile)
      out(`Restored apps/api/.env from ${result.apiEnvFile}`);
    if (result.mongoFile) out(`Restored MongoDB from ${result.mongoFile}`);
    if (result.postgresFile)
      out(`Restored PostgreSQL from ${result.postgresFile}`);
    for (const { label, file } of result.volumeFiles)
      out(`Restored ${label} from ${file}`);
    out(
      "Restore complete. Run 'gaia doctor' to confirm every dependency is ready.",
    );
  } catch (e) {
    printError((e as Error).message);
    process.exitCode = 1;
  }
}
