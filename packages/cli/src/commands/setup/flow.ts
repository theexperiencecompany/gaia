import { updateConfig } from "../../lib/config.js";
import { runEnvSetup, selectSetupMode } from "../../lib/env-setup.js";
import {
  createLogHandler,
  delay,
  runBasePrerequisiteChecks,
  runDeveloperPrerequisiteChecks,
  runMiseDeveloperSetup,
  runPortChecks,
} from "../../lib/flow-utils.js";
import { findRepoRoot } from "../../lib/service-starter.js";
import type { CLIStore } from "../../ui/store.js";

export async function runSetupFlow(store: CLIStore): Promise<void> {
  // 1. Detect repo root
  store.setStep("Detect Repo");
  store.setStatus("Looking for GAIA repository...");

  const repoPath = findRepoRoot();
  if (!repoPath) {
    store.setError(
      new Error(
        "Could not find GAIA repository. Run this command from within a cloned gaia repo, or use 'gaia init' to set up from scratch.",
      ),
    );
    return;
  }

  store.updateData("repoPath", repoPath);
  store.setStatus(`Found repository at ${repoPath}`);
  await delay(1000);

  // 2. Prerequisites
  store.setStep("Prerequisites");
  store.setStatus("Checking system requirements...");

  if (!(await runBasePrerequisiteChecks(store))) return;

  // Port check
  const portOverrides = await runPortChecks(store);
  if (portOverrides === null) return;

  // 3. Setup Mode
  const setupMode = await selectSetupMode(store);

  if (setupMode === "developer") {
    const developerPrereqs = await runDeveloperPrerequisiteChecks(store);
    if (!developerPrereqs) return;
  }

  // 4. Environment Setup
  await runEnvSetup(store, repoPath, setupMode, portOverrides);

  if (store.currentState.error) {
    return;
  }

  if (setupMode === "selfhost") {
    const envMethod = (store.currentState.data.envMethod as string) || "manual";
    updateConfig({
      setupComplete: true,
      setupMethod: envMethod as "manual" | "infisical",
      repoPath,
    });

    store.updateData("setupMode", setupMode);
    store.setStep("Finished");
    store.setStatus(
      "Setup complete! Run 'gaia start' to build and start all services in Docker.",
    );
    await store.waitForInput("exit");
    return;
  }

  // 4. Project Setup (developer mode only)
  const logHandler = createLogHandler(store);
  const ok = await runMiseDeveloperSetup(
    store,
    repoPath,
    portOverrides,
    logHandler,
  );
  if (!ok) return;

  await delay(1000);

  const envMethod = (store.currentState.data.envMethod as string) || "manual";
  updateConfig({
    setupComplete: true,
    setupMethod: envMethod as "manual" | "infisical",
    repoPath,
  });

  store.updateData("setupMode", setupMode);
  store.setStep("Finished");
  store.setStatus("Setup complete! Run 'gaia dev' to start development mode.");
  await store.waitForInput("exit");
}
