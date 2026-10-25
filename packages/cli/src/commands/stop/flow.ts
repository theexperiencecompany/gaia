import { setEnding } from "../../lib/command-ending.js";
import {
  COMPOSE_PROJECT_BY_MODE,
  getComposeProjectContainers,
} from "../../lib/docker.js";
import { getDockerAccess } from "../../lib/docker-access.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { detectSetupMode, findInstallRoot } from "../../lib/install-root.js";
import {
  endActiveStep,
  finishStep,
  initSteps,
  startStep,
  updateStep,
} from "../../lib/run-steps.js";
import {
  type StopServicesOptions,
  stopServices,
} from "../../lib/service-starter.js";
import { stopPhaseReporter } from "../../lib/start-steps.js";
import type { CLIStore } from "../../ui/store.js";

const STOP_STEP = {
  id: "stop",
  label: "Stopping GAIA",
  doneLabel: "Stopped GAIA",
} as const;

function fail(store: CLIStore, error: Error): void {
  endActiveStep(store, "failed");
  store.setError(error);
}

/** Whether no self-host container is running, so a stop has nothing to do. */
async function nothingRunning(repoPath: string): Promise<boolean> {
  if ((await detectSetupMode(repoPath)) !== "selfhost") return false;
  if ((await getDockerAccess()) !== "ready") return false;
  const containers = await getComposeProjectContainers(
    COMPOSE_PROJECT_BY_MODE.selfhost,
  );
  return !containers.some((container) => container.state === "running");
}

export async function runStopFlow(
  store: CLIStore,
  options?: StopServicesOptions,
): Promise<void> {
  initSteps(store, [STOP_STEP]);
  startStep(store, STOP_STEP.id);

  const repoPath = findInstallRoot();
  if (!repoPath) {
    fail(
      store,
      new Error(
        "GAIA isn't installed here, so there is nothing to stop.\nInstall it with 'gaia up'.",
      ),
    );
    return;
  }

  if (await nothingRunning(repoPath)) {
    finishStep(store, STOP_STEP.id, "GAIA wasn't running");
  } else {
    try {
      await stopServices(
        repoPath,
        (status) => updateStep(store, STOP_STEP.id, { detail: status }),
        readDockerComposePortOverrides(repoPath),
        options,
        stopPhaseReporter(store, STOP_STEP.id),
      );
    } catch (e) {
      fail(store, new Error(`GAIA didn't stop. ${(e as Error).message}`));
      return;
    }
    finishStep(store, STOP_STEP.id);
  }
  setEnding(store, {
    lead: "Start it again:",
    target: "gaia start",
    also: options?.forcePorts
      ? ["--force-ports also stopped whatever else listened on GAIA's ports."]
      : [],
  });
}
