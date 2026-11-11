/**
 * Handler for `gaia restore` — put a backup back into the self-host stack and
 * restart it, as steps on the shared run screen. --dry-run prints the
 * commands instead.
 * @module commands/restore/handler
 */

import { setEnding } from "../../lib/command-ending.js";
import { runCommandUI } from "../../lib/command-runner.js";
import {
  DEFAULT_WEB_PORT,
  installWebUrl,
  localApiUrl,
} from "../../lib/endpoints.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import {
  advanceSubstep,
  endActiveStep,
  findStep,
  finishStep,
  initSteps,
  startStep,
} from "../../lib/run-steps.js";
import {
  composePhaseReporter,
  START_STEP,
  waitForGaia,
} from "../../lib/start-steps.js";
import { MARK } from "../../ui/constants.js";
import { printHeader } from "../../ui/header/header-lines.js";
import type { CLIStore } from "../../ui/store.js";
import {
  getRestoreCommands,
  type RestoreOptions,
  resolveRestoreFiles,
  restoreParts,
  restoreWarnings,
  runRestore,
} from "./flow.js";

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

async function printDryRun(options: RestoreOptions): Promise<void> {
  await printHeader({ showStatus: false });
  const cmds = getRestoreCommands(resolveRestoreFiles(options));
  if (cmds.length === 0) {
    out(`  ${MARK.fail} No backup to restore was given.`);
    out(
      "    Point at the folder 'gaia backup' saved to: gaia restore --from <folder>",
    );
    return;
  }
  out(
    "  These commands would run, from the install's packages/cli/selfhost folder:",
  );
  for (const cmd of cmds) out(`    ${cmd}`);
}

async function runRestoreFlow(
  store: CLIStore,
  options: RestoreOptions,
): Promise<void> {
  const resolved = resolveRestoreFiles(options);
  const parts = restoreParts(resolved);
  initSteps(store, [
    {
      id: "restore",
      label: "Restoring your data",
      doneLabel: "Restored your data",
    },
    START_STEP,
  ]);
  startStep(store, "restore");
  let restored: { repoPath: string; startedServices: number };
  try {
    const onCompose = composePhaseReporter(store);
    restored = await runRestore(options, {
      onPart: (id) => advanceSubstep(store, "restore", parts, id),
      onRestart: (phase) => {
        // The restart begins once every part is back.
        if (findStep(store, "restore")?.state === "active") {
          finishStep(store, "restore");
        }
        onCompose(phase);
      },
    });
  } catch (e) {
    endActiveStep(store, "failed");
    store.setError(e as Error);
    return;
  }
  const { repoPath, startedServices } = restored;
  const ports = readDockerComposePortOverrides(repoPath);
  const webPort = ports[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  const readiness = await waitForGaia(
    store,
    { apiUrl: localApiUrl("selfhost", ports), webPort },
    startedServices,
  );
  if (!readiness.ready) {
    store.setError(
      new Error(
        "Your data is back, but GAIA didn't answer in time after the restart.\n'gaia status' shows which part is down; 'gaia logs' shows why.",
      ),
    );
    return;
  }
  setEnding(store, {
    lead: "Open:",
    target: installWebUrl(repoPath, webPort),
    also: restoreWarnings(resolved),
  });
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
  if (options.dryRun) {
    await printDryRun(restoreOptions);
    return;
  }
  await runCommandUI({
    command: "run",
    whenNonInteractive: "plain",
    runFlow: (store) => runRestoreFlow(store, restoreOptions),
    cancelHint:
      "The restore stopped part way. Run the same 'gaia restore' again to finish it.",
  });
}
