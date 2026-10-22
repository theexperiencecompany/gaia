import { LOG_BUFFER_LINES } from "../ui/constants.js";
import type { CLIStore } from "../ui/store.js";
import { runCommand } from "./child-process.js";
import type { SetupMode } from "./env-parser.js";
import { portOverridesToDockerEnv } from "./env-writer.js";
import { resolvePortConflicts } from "./port-conflicts.js";
import type { PortPlan } from "./port-conflicts.types.js";
import { ensurePrerequisites } from "./prerequisite-install.js";
import * as prereqs from "./prerequisites.js";
import type { StartProgress } from "./service-starter.js";

export const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export const createLogHandler = (store: CLIStore) => (chunk: string) => {
  const currentLogs = store.currentState.data.dependencyLogs ?? [];
  const lines = chunk.split("\n").filter((line) => line.trim() !== "");
  store.updateData(
    "dependencyLogs",
    [...currentLogs, ...lines].slice(-LOG_BUFFER_LINES),
  );
};

/** A compose progress callback driving the dependency step's phase line, bar and finished list. */
export function dependencyStepProgress(store: CLIStore): StartProgress {
  return (phase, finished) => {
    store.updateData("dependencyPhase", phase.label);
    store.updateData("dependencyProgress", phase.percent);
    store.updateData("dependencyLogs", finished.slice(-LOG_BUFFER_LINES));
  };
}

/**
 * Ensures git and Docker, each with an install offer on apt-based Linux.
 * Sets the store error and returns false when setup cannot continue (or
 * stops for a docker-group relaunch).
 */
export async function runBasePrerequisiteChecks(
  store: CLIStore,
): Promise<boolean> {
  store.updateData("checks", { git: "pending" });

  await delay(500);

  try {
    // "relaunch": the command runner restarts this command with the docker
    // group active, so this run stops here without an error.
    return (await ensurePrerequisites(store, { needGit: true })) === "ready";
  } catch (e) {
    store.setError(e as Error);
    return false;
  }
}

/**
 * Runs developer-only Mise prerequisite checks and auto-installs when missing.
 * Sets store error and returns null if setup cannot continue.
 */
export async function runDeveloperPrerequisiteChecks(
  store: CLIStore,
): Promise<"success" | null> {
  store.updateData("checks", {
    ...store.currentState.data.checks,
    mise: "pending",
  });

  let miseStatus = await prereqs.checkMise();
  store.updateData("checks", {
    ...store.currentState.data.checks,
    mise: miseStatus,
  });

  if (miseStatus === "missing") {
    store.setStatus("Installing Mise…");
    const installed = await prereqs.installMise();
    miseStatus = installed ? "success" : "error";
    store.updateData("checks", {
      ...store.currentState.data.checks,
      mise: miseStatus,
    });
  }

  if (miseStatus === "error") {
    store.setError(
      new Error(
        `Developer mode requires Mise but it failed to install.\n  • Mise: ${prereqs.PREREQUISITE_URLS.mise}`,
      ),
    );
    return null;
  }

  return "success";
}

/** The host ports to bind, and one line per port moved off a taken one. */
export interface PortChecks {
  overrides: Record<number, number>;
  moved: string[];
}

const ASK_ABOUT_CONFLICTS: PortPlan = { planned: {}, fixed: {}, policy: "ask" };

/**
 * Check the ports the plan will bind and settle conflicts by its policy.
 * Sets the store error and returns null when a port can't be settled or the user aborts.
 */
export async function runPortChecks(
  store: CLIStore,
  mode: SetupMode,
  plan: PortPlan = ASK_ABOUT_CONFLICTS,
): Promise<PortChecks | null> {
  store.setStatus("Checking ports…");
  const portResults = await prereqs.checkModePorts(mode, plan.planned);
  const resolution = resolvePortConflicts(portResults, plan);
  if ("error" in resolution) {
    store.setError(new Error(resolution.error));
    return null;
  }

  if (plan.policy === "ask" && resolution.moved.length > 0) {
    store.updateData("portConflicts", portResults);
    const answer = await store.waitForInput("port_conflicts");
    if (answer === "abort") {
      store.setError(
        new Error(
          "Port conflicts not resolved. Please free the ports and try again.",
        ),
      );
      return null;
    }
  }

  store.updateData("portOverrides", resolution.overrides);
  return resolution;
}

/**
 * Runs mise trust + install + the bootstrap task for developer mode.
 * Returns true on success, false on failure (store error is set).
 */
export async function runMiseDeveloperSetup(
  store: CLIStore,
  repoPath: string,
  portOverrides: Record<number, number>,
  logHandler: (chunk: string) => void,
): Promise<boolean> {
  store.setStep("Project Setup");
  store.updateData("dependencyPhase", "Setting up project…");
  store.updateData("dependencyProgress", 0);
  store.updateData("dependencyComplete", false);
  store.updateData("dependencyLogs", []);

  try {
    store.updateData("dependencyPhase", "Trusting mise configuration…");
    await runCommand("mise", ["trust"], { cwd: repoPath, onLog: logHandler });
    store.updateData("dependencyProgress", 20);

    store.updateData("dependencyPhase", "Installing tools…");
    await runCommand("mise", ["install"], {
      cwd: repoPath,
      onProgress: (progress) => {
        store.updateData("dependencyProgress", 20 + progress * 0.3);
      },
      onLog: logHandler,
    });

    store.updateData("dependencyPhase", "Running mise run bootstrap…");
    const dockerEnv =
      Object.keys(portOverrides).length > 0
        ? portOverridesToDockerEnv(portOverrides)
        : undefined;

    await runCommand("mise", ["run", "bootstrap"], {
      cwd: repoPath,
      onProgress: (progress) => {
        store.updateData("dependencyProgress", 50 + progress * 0.5);
      },
      onLog: logHandler,
      env: dockerEnv,
    });

    store.updateData("dependencyProgress", 100);
    store.updateData("dependencyPhase", "Set up");
    store.updateData("dependencyComplete", true);
    return true;
  } catch (e) {
    store.setError(
      new Error(`Failed to setup project: ${(e as Error).message}`),
    );
    return false;
  }
}
