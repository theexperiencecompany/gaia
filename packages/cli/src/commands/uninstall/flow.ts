/**
 * `gaia uninstall` — remove a self-host install: its containers, networks
 * and images, the gaia.local name, the install folder and ~/.gaia. The data
 * (Docker volumes) goes only when the user says so, after an offer to back
 * it up; kept data keeps the settings files that unlock it.
 * @module commands/uninstall/flow
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { resolveRecordedInstall } from "../../lib/answers.js";
import { GAIA_CONFIG_DIR, readConfig } from "../../lib/config.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { isSelfhostOrUnconfigured } from "../../lib/install-root.js";
import { localNameLabel, removeLocalName } from "../../lib/local-name.js";
import { isInteractive } from "../../lib/non-tty.js";
import { homeRelative } from "../../lib/paths.js";
import {
  advanceSubstep,
  endActiveStep,
  finishStep,
  initSteps,
  type RunStep,
  startStep,
  updateStep,
} from "../../lib/run-steps.js";
import { stopServices } from "../../lib/service-starter.js";
import { stopPhaseReporter } from "../../lib/start-steps.js";
import type { CLIStore } from "../../ui/store.js";
import type { AnswerResolver } from "../../ui/store.types.js";
import { BACKUP_PARTS, runBackup } from "../backup/flow.js";

export interface UninstallOptions {
  /** Answer every question: uninstall, keep the data, no backup. */
  yes?: boolean;
  /** Delete the data (Docker volumes) too. */
  deleteData?: boolean;
}

/** The three questions, asked in order; the data questions default to keeping it. */
export const UNINSTALL_INPUTS = {
  confirm: "uninstall_confirm",
  deleteData: "uninstall_delete_data",
  backup: "uninstall_backup",
} as const;

export type UninstallInputId =
  (typeof UNINSTALL_INPUTS)[keyof typeof UNINSTALL_INPUTS];

export const UNINSTALL_OUTCOME_KEY = "uninstallOutcome";

/** Where an uninstall's backup goes: outside the install folder it deletes. */
export const UNINSTALL_BACKUP_DIR = path.join(os.homedir(), "gaia-backups");

/** The settings kept with kept data: the secrets and passwords its volumes were made with. */
export const KEPT_SETTINGS_FILES = ["apps/api/.env", "infra/docker/.env"];

export const CLI_REMOVE_COMMAND = "npm rm -g @heygaia/cli";

/** Deletes the volumes kept by an uninstall, once they are no longer wanted. */
export const KEPT_DATA_REMOVE_COMMAND =
  "docker volume rm $(docker volume ls -q --filter label=com.docker.compose.project=gaia-selfhost)";

export interface UninstallOutcome {
  /** The install folder; with kept data, where its settings files stay. */
  installDir: string | null;
  keptData: boolean;
  backupDir?: string;
}

/**
 * Delete the install, or with keepSettings everything in it except
 * KEPT_SETTINGS_FILES, so a later `gaia up` there finds the kept data's secrets.
 */
export function removeInstallFiles(
  installDir: string,
  options: { keepSettings: boolean },
): void {
  if (!options.keepSettings) {
    fs.rmSync(installDir, { recursive: true, force: true });
    return;
  }
  const kept = KEPT_SETTINGS_FILES.map((file) => path.join(installDir, file));
  const keptPaths = new Set(kept);
  const prune = (dir: string): void => {
    for (const entry of fs.readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (keptPaths.has(full)) continue;
      const holdsKept = kept.some((file) =>
        file.startsWith(`${full}${path.sep}`),
      );
      if (holdsKept) prune(full);
      else fs.rmSync(full, { recursive: true, force: true });
    }
  };
  prune(installDir);
}

/** --yes and --delete-data answer the questions; anything left is asked. */
function flagAnswers(options: UninstallOptions): AnswerResolver {
  return {
    [UNINSTALL_INPUTS.confirm]: () => (options.yes ? true : undefined),
    [UNINSTALL_INPUTS.deleteData]: () =>
      options.deleteData ? true : options.yes ? false : undefined,
    [UNINSTALL_INPUTS.backup]: () => (options.yes ? false : undefined),
  };
}

/** One uninstall step: what the list shows, and the work it stands for. */
interface UninstallTask
  extends Pick<RunStep, "id" | "label" | "doneLabel" | "minor"> {
  run: () => Promise<unknown> | void;
}

/** What the user chose, from the questions or the flags. */
interface UninstallChoice {
  deleteData: boolean;
  backup: boolean;
}

/** The steps this uninstall runs, in order; the backup goes first, while GAIA still runs. */
function uninstallTasks(
  store: CLIStore,
  installDir: string | null,
  /** How copy names the .local name to remove; null when none was set up. */
  localName: string | null,
  { deleteData, backup }: UninstallChoice,
): UninstallTask[] {
  const tasks: UninstallTask[] = [];
  if (backup) {
    tasks.push({
      id: "backup",
      label: "Backing up your data",
      doneLabel: `Backed up your data to ${homeRelative(UNINSTALL_BACKUP_DIR)}`,
      run: () =>
        runBackup({
          outputDir: UNINSTALL_BACKUP_DIR,
          onPart: (id) => advanceSubstep(store, "backup", BACKUP_PARTS, id),
        }),
    });
  }
  if (installDir) {
    // Short enough for the step list's label column (31 columns).
    const what = deleteData ? "containers and data" : "containers and images";
    tasks.push({
      id: "containers",
      label: `Removing ${what}`,
      doneLabel: `Removed ${what}`,
      run: () =>
        stopServices(
          installDir,
          (status) => updateStep(store, "containers", { detail: status }),
          readDockerComposePortOverrides(installDir),
          { remove: { volumes: deleteData } },
          stopPhaseReporter(store, "containers"),
        ),
    });
  }
  if (localName) {
    tasks.push({
      id: "local-name",
      label: `Removing ${localName}`,
      doneLabel: `Removed ${localName}`,
      minor: true,
      run: removeLocalName,
    });
  }
  if (installDir) {
    const shown = homeRelative(installDir);
    tasks.push({
      id: "files",
      label: `Removing ${shown}`,
      doneLabel: deleteData
        ? `Removed ${shown}`
        : `Removed ${shown}, except its settings`,
      minor: true,
      run: () => removeInstallFiles(installDir, { keepSettings: !deleteData }),
    });
  }
  tasks.push({
    id: "config",
    label: `Removing ${homeRelative(GAIA_CONFIG_DIR)}`,
    doneLabel: `Removed ${homeRelative(GAIA_CONFIG_DIR)}`,
    minor: true,
    run: () => fs.rmSync(GAIA_CONFIG_DIR, { recursive: true, force: true }),
  });
  return tasks;
}

/** Run the tasks in order; the first error turns its step red, shows, and stops the rest. */
async function runTasks(
  store: CLIStore,
  tasks: UninstallTask[],
): Promise<boolean> {
  initSteps(store, tasks);
  for (const task of tasks) {
    startStep(store, task.id);
    try {
      await task.run();
    } catch (e) {
      endActiveStep(store, "failed");
      store.setError(e as Error);
      return false;
    }
    finishStep(store, task.id);
  }
  return true;
}

/** The recorded self-host install, or the error saying why there is nothing this command may remove. */
async function findUninstallTarget(): Promise<
  { installDir: string | null } | { error: Error }
> {
  const installDir = resolveRecordedInstall();
  if (!installDir && !readConfig()) {
    return {
      error: new Error(
        "GAIA isn't installed here, so there is nothing to uninstall.",
      ),
    };
  }
  if (installDir && !(await isSelfhostOrUnconfigured(installDir))) {
    return {
      error: new Error(
        `${homeRelative(installDir)} is not a self-host install (its apps/api/.env is in developer mode or names no mode), and 'gaia uninstall' removes only self-host installs.\nDelete it yourself if you no longer need it.`,
      ),
    };
  }
  return { installDir };
}

/** Ask the three questions in turn; null when the user says no to uninstalling. */
async function askChoice(store: CLIStore): Promise<UninstallChoice | null> {
  if ((await store.waitForInput(UNINSTALL_INPUTS.confirm)) !== true)
    return null;
  const deleteData =
    (await store.waitForInput(UNINSTALL_INPUTS.deleteData)) === true;
  const backup =
    deleteData && (await store.waitForInput(UNINSTALL_INPUTS.backup)) === true;
  return { deleteData, backup };
}

export async function runUninstallFlow(
  store: CLIStore,
  options: UninstallOptions = {},
): Promise<void> {
  if (!isInteractive() && !options.yes) {
    store.setError(
      new Error(
        "There is no terminal to confirm in.\nRerun with --yes (keeps your data) or --yes --delete-data.",
      ),
    );
    return;
  }
  const target = await findUninstallTarget();
  if ("error" in target) {
    store.setError(target.error);
    return;
  }
  const { installDir } = target;
  const recorded = readConfig()?.localName;
  const localName = recorded ? localNameLabel(recorded) : null;

  store.updateData("installDir", installDir);
  store.pushAnswerResolver(flagAnswers(options));
  const choice = await askChoice(store);
  if (!choice) {
    store.setStatus("Nothing was removed.");
    store.updateData("cancelled", true);
    return;
  }
  if (
    !(await runTasks(
      store,
      uninstallTasks(store, installDir, localName, choice),
    ))
  ) {
    return;
  }
  const outcome: UninstallOutcome = {
    installDir,
    keptData: !choice.deleteData,
    ...(choice.backup ? { backupDir: UNINSTALL_BACKUP_DIR } : {}),
  };
  store.updateData(UNINSTALL_OUTCOME_KEY, outcome);
  store.updateData("finished", true);
}
