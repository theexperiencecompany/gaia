import type { CLIStore } from "../../ui/store.js";
import * as prereqs from "../../lib/prerequisites.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import {
  startServices,
  areServicesRunning,
  runCommand,
  findRepoRoot,
} from "../../lib/service-starter.js";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

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

  store.updateData("checks", {
    git: "pending",
    docker: "pending",
    mise: "pending",
  });

  await delay(500);

  const gitStatus = await prereqs.checkGit();
  store.updateData("checks", {
    ...store.currentState.data.checks,
    git: gitStatus,
  });

  const dockerStatus = await prereqs.checkDocker();
  store.updateData("checks", {
    ...store.currentState.data.checks,
    docker: dockerStatus,
  });

  let miseStatus = await prereqs.checkMise();
  store.updateData("checks", {
    ...store.currentState.data.checks,
    mise: miseStatus,
  });

  if (miseStatus === "missing") {
    store.setStatus("Installing Mise...");
    const installed = await prereqs.installMise();
    miseStatus = installed ? "success" : "error";
    store.updateData("checks", {
      ...store.currentState.data.checks,
      mise: miseStatus,
    });
  }

  // Port check
  store.setStatus("Checking Ports...");
  const requiredPorts = [8000, 5432, 6379, 27017, 5672, 3000];
  const portResults = await prereqs.checkPortsWithFallback(requiredPorts);
  const portOverrides: Record<number, number> = {};
  const conflicts = portResults.filter((r) => !r.available);

  if (conflicts.length > 0) {
    store.updateData("portConflicts", portResults);
    const resolution = (await store.waitForInput("port_conflicts")) as
      | "accept"
      | "abort";

    if (resolution === "abort") {
      store.setError(
        new Error("Port conflicts not resolved."),
      );
      return;
    }

    for (const result of portResults) {
      if (!result.available && result.alternative) {
        portOverrides[result.port] = result.alternative;
      }
    }
  }

  if (
    gitStatus === "error" ||
    dockerStatus === "error" ||
    miseStatus === "error"
  ) {
    store.setError(new Error("Prerequisites failed"));
    return;
  }

  store.setStatus("Prerequisites check complete!");
  await delay(1000);

  // 3. Environment Setup
  await runEnvSetup(store, repoPath, portOverrides);

  // 4. Project Setup (mise setup)
  store.setStep("Project Setup");
  store.updateData("dependencyPhase", "Setting up project...");
  store.updateData("dependencyProgress", 0);
  store.updateData("dependencyComplete", false);
  store.updateData("dependencyLogs", []);

  const logHandler = (chunk: string) => {
    const currentLogs = store.currentState.data.dependencyLogs || [];
    const lines = chunk.split("\n").filter((line: string) => line.trim() !== "");
    const newLogs = [...currentLogs, ...lines].slice(-10);
    store.updateData("dependencyLogs", newLogs);
  };

  try {
    store.updateData("dependencyPhase", "Trusting mise configuration...");
    await runCommand("mise", ["trust"], repoPath, undefined, logHandler);
    store.updateData("dependencyProgress", 20);

    store.updateData("dependencyPhase", "Installing tools...");
    await runCommand(
      "mise",
      ["install"],
      repoPath,
      (progress) => {
        store.updateData("dependencyProgress", 20 + progress * 0.3);
      },
      logHandler,
    );

    store.updateData("dependencyPhase", "Running mise setup...");
    await runCommand(
      "mise",
      ["setup"],
      repoPath,
      (progress) => {
        store.updateData("dependencyProgress", 50 + progress * 0.5);
      },
      logHandler,
    );

    store.updateData("dependencyProgress", 100);
    store.updateData("dependencyPhase", "Setup complete!");
    store.updateData("dependencyComplete", true);
  } catch (e) {
    store.setError(
      new Error(`Failed to setup project: ${(e as Error).message}`),
    );
    return;
  }

  await delay(1000);

  // 5. Check if services are already running, otherwise offer to start
  store.setStatus("Checking if services are already running...");
  const alreadyRunning = await areServicesRunning(repoPath);

  if (alreadyRunning) {
    store.updateData("servicesAlreadyRunning", true);
    store.setStep("Finished");
    store.setStatus("Setup complete!");
  } else {
    store.setStep("Start Services");
    store.setStatus("Ready to start GAIA");

    const startChoice = (await store.waitForInput("start_services")) as string;
    const setupMode = store.currentState.data.setupMode || "developer";

    if (startChoice === "start") {
      store.setStatus("Starting GAIA...");
      try {
        await startServices(repoPath, setupMode, (status) => {
          store.setStatus(status);
        });
        store.setStatus("GAIA is running!");
        await store.waitForInput("services_running");
      } catch (e) {
        store.setError(
          new Error(`Failed to start services: ${(e as Error).message}`),
        );
        return;
      }
    } else {
      await store.waitForInput("manual_commands");
    }

    store.setStep("Finished");
    store.setStatus("Setup complete!");
  }
}
