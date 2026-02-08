import type { CLIStore } from "../../ui/store.js";
import * as prereqs from "../../lib/prerequisites.js";
import * as git from "../../lib/git.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import {
  startServices,
  areServicesRunning,
  checkUrl,
  runCommand,
  findRepoRoot,
} from "../../lib/service-starter.js";

import * as fs from "fs";
import * as path from "path";

const DEV_MODE = process.env.GAIA_CLI_DEV === "true";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export async function runInitFlow(store: CLIStore): Promise<void> {
  // 0. Welcome
  store.setStep("Welcome");
  store.setStatus("Waiting for user input...");
  await store.waitForInput("welcome");

  const logHandler = (chunk: string) => {
    const currentLogs = store.currentState.data.dependencyLogs || [];
    const lines = chunk.split("\n").filter((line: string) => line.trim() !== "");
    const newLogs = [...currentLogs, ...lines].slice(-10);
    store.updateData("dependencyLogs", newLogs);
  };

  // 1. Prerequisites
  store.setStep("Prerequisites");
  store.setStatus("Checking system requirements...");

  store.updateData("checks", {
    git: "pending",
    docker: "pending",
    mise: "pending",
  });

  await delay(800);

  store.setStatus("Checking Git...");
  const gitStatus = await prereqs.checkGit();
  store.updateData("checks", {
    ...store.currentState.data.checks,
    git: gitStatus,
  });

  store.setStatus("Checking Docker...");
  const dockerStatus = await prereqs.checkDocker();
  store.updateData("checks", {
    ...store.currentState.data.checks,
    docker: dockerStatus,
  });

  store.setStatus("Checking Mise...");
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

  // Check Ports
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
        new Error("Port conflicts not resolved. Please free the ports and try again."),
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

  let repoPath = "";

  if (DEV_MODE) {
    repoPath = findRepoRoot() || "";
    if (!repoPath) {
      store.setError(
        new Error(
          "DEV_MODE: Could not find workspace root. Run from within the gaia repo.",
        ),
      );
      return;
    }
    store.setStep("Repository Setup");
    store.setStatus("[DEV MODE] Using current workspace...");
    await delay(500);
    store.setStatus("Repository ready!");
  } else {
    while (true) {
      repoPath = (await store.waitForInput("repo_path", {
        default: "./gaia",
      })) as string;
      if (fs.existsSync(repoPath)) {
        const stat = fs.statSync(repoPath);
        if (!stat.isDirectory()) {
          store.setError(
            new Error(`Path ${repoPath} exists and is not a directory.`),
          );
          await delay(2000);
          store.setError(null);
          continue;
        }

        const files = fs.readdirSync(repoPath);
        if (files.length > 0) {
          store.setError(
            new Error(
              `Directory ${repoPath} is not empty. Please choose another path.`,
            ),
          );
          await delay(2000);
          store.setError(null);
          continue;
        }
      }
      break;
    }

    store.setStep("Repository Setup");
    store.setStatus("Preparing repository...");
    store.updateData("repoProgress", 0);
    store.updateData("repoPhase", "");

    try {
      await git.setupRepo(
        repoPath,
        "https://github.com/theexperiencecompany/gaia.git",
        (progress, phase) => {
          store.updateData("repoProgress", progress);
          if (phase) {
            store.updateData("repoPhase", phase);
            store.setStatus(`${phase}...`);
          } else {
            store.setStatus(`Cloning repository to ${repoPath}... ${progress}%`);
          }
        },
      );
      store.setStatus("Repository ready!");
    } catch (e) {
      store.setError(e as Error);
      return;
    }
  }

  await delay(1000);

  // 2.5 Install Tools
  store.setStep("Install Tools");
  store.setStatus("Installing toolchain...");
  store.updateData("dependencyPhase", "Initializing mise...");
  store.updateData("dependencyProgress", 0);
  store.updateData("dependencyLogs", []);

  try {
    store.updateData("dependencyPhase", "Trusting mise configuration...");
    await runCommand("mise", ["trust"], repoPath, undefined, logHandler);
    store.updateData("dependencyProgress", 50);

    store.updateData(
      "dependencyPhase",
      "Installing tools (node, python, uv, nx)...",
    );
    await runCommand(
      "mise",
      ["install"],
      repoPath,
      (progress) => {
        store.updateData("dependencyProgress", 50 + progress * 0.5);
      },
      logHandler,
    );

    store.updateData("dependencyProgress", 100);
    store.updateData("toolComplete", true);
  } catch (e) {
    store.setError(
      new Error(`Failed to install tools: ${(e as Error).message}`),
    );
    return;
  }

  await delay(1000);

  // 3. Environment Setup (shared)
  await runEnvSetup(store, repoPath, portOverrides);

  // 4. Project Setup
  store.setStep("Project Setup");
  store.updateData("dependencyPhase", "Setting up project...");
  store.updateData("dependencyProgress", 0);
  store.updateData("dependencyComplete", false);
  store.updateData("repoPath", repoPath);
  store.updateData("dependencyLogs", []);

  try {
    store.updateData("dependencyProgress", 0);
    store.updateData(
      "dependencyPhase",
      "Running mise setup (all dependencies)...",
    );

    await runCommand(
      "mise",
      ["setup"],
      repoPath,
      (progress) => {
        store.updateData("dependencyProgress", progress);
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
  const setupMode = store.currentState.data.setupMode || "developer";

  if (alreadyRunning) {
    store.updateData("servicesAlreadyRunning", true);
    store.setStep("Finished");
    store.setStatus("Setup complete!");
  } else {
    store.setStep("Start Services");
    store.setStatus("Ready to start GAIA");

    const startChoice = (await store.waitForInput("start_services")) as string;

    if (startChoice === "start") {
      store.setStatus("Starting GAIA...");

      try {
        await startServices(repoPath, setupMode, (status) => {
          store.setStatus(status);
        });

        await delay(1000);
        store.setStatus("GAIA is running!");
        await store.waitForInput("services_running");
      } catch (e) {
        store.setError(
          new Error(`Failed to start services: ${(e as Error).message}`),
        );
        return;
      }

      // Health Checks
      store.setStatus("Verifying deployment...");
      const apiHealth = await checkUrl("http://localhost:8000/health");
      const webHealth = await checkUrl("http://localhost:3000");

      if (!apiHealth || !webHealth) {
        store.setStatus(
          `Warning: Services might not be ready. API: ${apiHealth ? "UP" : "DOWN"}, Web: ${webHealth ? "UP" : "DOWN"}`,
        );
        await delay(3000);
      } else {
        store.setStatus("All systems operational!");
        await delay(1500);
      }
    } else {
      await store.waitForInput("manual_commands");
    }

    store.setStep("Finished");
    store.setStatus("Setup complete!");
  }
}
