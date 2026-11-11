import { setEnding } from "../../lib/command-ending.js";
import { dockerAccessError, getDockerAccess } from "../../lib/docker-access.js";
import {
  DEFAULT_WEB_PORT,
  installWebUrl,
  localApiUrl,
} from "../../lib/endpoints.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { detectSetupMode, findInstallRoot } from "../../lib/install-root.js";
import {
  endActiveStep,
  finishStep,
  initSteps,
  startStep,
} from "../../lib/run-steps.js";
import type { StartServicesOptions } from "../../lib/service-starter.js";
import {
  imagesStep,
  START_STEP,
  startSelfhostServices,
  waitForGaia,
} from "../../lib/start-steps.js";
import type { CLIStore } from "../../ui/store.js";

function fail(store: CLIStore, error: Error): void {
  endActiveStep(store, "failed");
  store.setError(error);
}

export async function runStartFlow(
  store: CLIStore,
  options: StartServicesOptions = {},
): Promise<void> {
  initSteps(store, [
    {
      id: "docker",
      label: "Checking Docker",
      doneLabel: "Docker is ready",
      minor: true,
    },
    imagesStep(options.build === true),
    START_STEP,
  ]);
  startStep(store, "docker");

  const repoPath = findInstallRoot();
  if (!repoPath) {
    fail(
      store,
      new Error(
        "GAIA isn't installed here, so there is nothing to start.\nInstall it with 'gaia up'.",
      ),
    );
    return;
  }
  const mode = await detectSetupMode(repoPath);
  if (mode !== "selfhost") {
    fail(
      store,
      new Error(
        mode === "developer"
          ? "This is a development copy of GAIA, which runs in the foreground.\nStart it with 'gaia dev' (or 'gaia dev full')."
          : "This GAIA install isn't set up yet.\nFinish it with 'gaia up'.",
      ),
    );
    return;
  }
  const access = await getDockerAccess();
  if (access !== "ready") {
    fail(store, await dockerAccessError(access));
    return;
  }
  finishStep(store, "docker");

  const portOverrides = readDockerComposePortOverrides(repoPath);
  const webPort = portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  let startedServices: number;
  try {
    startedServices = await startSelfhostServices(
      store,
      repoPath,
      portOverrides,
      { ...options, rebuildCommand: "gaia start --build" },
    );
  } catch (e) {
    fail(store, new Error(`GAIA didn't start. ${(e as Error).message}`));
    return;
  }
  const readiness = await waitForGaia(
    store,
    { apiUrl: localApiUrl("selfhost", portOverrides), webPort },
    startedServices,
  );
  if (!readiness.ready) {
    store.setError(
      new Error(
        "GAIA started but didn't answer in time.\n'gaia status' shows which part is down; 'gaia logs' shows why.",
      ),
    );
    return;
  }
  setEnding(store, {
    lead: "Open:",
    target: installWebUrl(repoPath, webPort),
    also: ["gaia status checks its health · gaia stop stops it"],
  });
}
