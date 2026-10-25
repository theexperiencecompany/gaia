/**
 * Handler for `gaia backup` — dump the databases, archive the storage
 * volumes and copy the settings that unlock them, as one step on the shared
 * run screen. --dry-run prints the commands instead.
 * @module commands/backup/handler
 */

import * as path from "node:path";
import { setEnding } from "../../lib/command-ending.js";
import { runCommandUI } from "../../lib/command-runner.js";
import { homeRelative } from "../../lib/paths.js";
import {
  advanceSubstep,
  endActiveStep,
  finishStep,
  initSteps,
  startStep,
} from "../../lib/run-steps.js";
import { VOLUME_BACKUPS } from "../../lib/volume-backups.js";
import { printHeader } from "../../ui/header/header-lines.js";
import type { CLIStore } from "../../ui/store.js";
import { BACKUP_PARTS, runBackup } from "./flow.js";

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

async function printDryRun(outputDir: string | undefined): Promise<void> {
  await printHeader({ showStatus: false });
  const result = await runBackup({ outputDir, dryRun: true });
  out("  These commands would run, from the install's infra/docker folder:");
  for (const cmd of result.commands) out(`    ${cmd}`);
  out(
    `  Volumes not created yet (${VOLUME_BACKUPS.map((v) => v.label).join(", ")}) are skipped.`,
  );
}

async function runBackupFlow(
  store: CLIStore,
  outputDir: string | undefined,
): Promise<void> {
  initSteps(store, [
    {
      id: "backup",
      label: "Backing up your data",
      doneLabel: "Backed up your data",
    },
  ]);
  startStep(store, "backup");
  try {
    const result = await runBackup({
      outputDir,
      onPart: (id) => advanceSubstep(store, "backup", BACKUP_PARTS, id),
    });
    const folder = homeRelative(path.dirname(result.mongoFile));
    finishStep(store, "backup", `Backed up your data to ${folder}`);
    setEnding(store, {
      lead: "Restore it with:",
      target: `gaia restore --from ${folder}`,
      also: [
        "Keep the folder private: it holds the key that unlocks your saved accounts.",
        ...result.warnings,
      ],
    });
  } catch (e) {
    endActiveStep(store, "failed");
    store.setError(e as Error);
  }
}

export async function runBackupCommand(
  options: { output?: string; dryRun?: boolean } = {},
): Promise<void> {
  if (options.dryRun) {
    await printDryRun(options.output);
    return;
  }
  await runCommandUI({
    command: "run",
    whenNonInteractive: "plain",
    runFlow: (store) => runBackupFlow(store, options.output),
    cancelHint: "The backup is incomplete; your last full backup is untouched.",
  });
}
