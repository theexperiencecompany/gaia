import { LOG_BUFFER_LINES } from "../ui/constants.js";
import type { CLIStore } from "../ui/store.js";
import { portOverridesToDockerEnv } from "./env-writer.js";
import * as prereqs from "./prerequisites.js";
import { runCommand } from "./service-starter.js";

export const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export const createLogHandler =
  (store: CLIStore, dataKey = "dependencyLogs") =>
  (chunk: string) => {
    const currentLogs: string[] = store.currentState.data[dataKey] || [];
    const lines = chunk
      .split("\n")
      .filter((line: string) => line.trim() !== "");
    store.updateData(
      dataKey,
      [...currentLogs, ...lines].slice(-LOG_BUFFER_LINES),
    );
  };

/**
 * Runs git and docker prerequisite checks.
 * Sets store error and returns null on hard failure (git or docker missing).
 */
export async function runBasePrerequisiteChecks(store: CLIStore): Promise<{
  gitStatus: string;
  dockerStatus: string;
  dockerInfo: Awaited<ReturnType<typeof prereqs.checkDockerDetailed>>;
} | null> {
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

  const dockerInfo = await prereqs.checkDockerDetailed();
  const dockerStatus = dockerInfo.working ? "success" : "error";
  store.updateData("checks", {
    ...store.currentState.data.checks,
    docker: dockerStatus,
  });
  if (!dockerInfo.working) {
    store.updateData("dockerError", dockerInfo.errorMessage);
  }

  const failedChecks: Array<{ name: string; message?: string }> = [];
  if (gitStatus === "error") failedChecks.push({ name: "Git" });
  if (dockerStatus === "error")
    failedChecks.push({ name: "Docker", message: dockerInfo.errorMessage });

  if (failedChecks.length > 0) {
    const errorLines: string[] = ["Prerequisites failed:"];
    for (const check of failedChecks) {
      errorLines.push(
        `  • ${check.name}: ${check.message || "Not installed or not working"}`,
      );
    }
    errorLines.push("\nInstallation guides:");
    if (gitStatus === "error")
      errorLines.push(`  • Git: ${prereqs.PREREQUISITE_URLS.git}`);
    if (dockerStatus === "error") {
      if (dockerInfo.installed) {
        errorLines.push(
          `  • Docker: Start Docker Desktop or run 'sudo systemctl start docker'`,
        );
      } else {
        errorLines.push(`  • Docker: ${prereqs.PREREQUISITE_URLS.docker}`);
      }
    }
    store.setError(new Error(errorLines.join("\n")));
    return null;
  }

  return { gitStatus, dockerStatus, dockerInfo };
}

/**
 * Runs developer-only Mise prerequisite checks and auto-installs when missing.
 * Sets store error and returns null if setup cannot continue.
 */
export async function runDeveloperPrerequisiteChecks(
  store: CLIStore,
): Promise<"success" | null> {
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

/**
 * Runs port conflict checks. Updates the store and returns portOverrides.
 * Sets store error and returns null on unresolvable conflicts or user abort.
 */
export async function runPortChecks(
  store: CLIStore,
): Promise<Record<number, number> | null> {
  store.setStatus("Checking Ports...");
  const requiredPorts = [8000, 5432, 6379, 27017, 5672, 3000, 8080, 8083];
  const portResults = await prereqs.checkPortsWithFallback(requiredPorts);
  const portOverrides: Record<number, number> = {};
  const conflicts = portResults.filter((r) => !r.available);

  if (conflicts.length > 0) {
    const unresolvable = conflicts.filter((r) => !r.alternative);
    if (unresolvable.length > 0) {
      store.setError(
        new Error(
          `Cannot find free alternative ports for: ${unresolvable.map((r) => `${r.port} (${r.service})`).join(", ")}. Free these ports and try again.`,
        ),
      );
      return null;
    }

    store.updateData("portConflicts", portResults);
    const resolution = (await store.waitForInput("port_conflicts")) as
      | "accept"
      | "abort";

    if (resolution === "abort") {
      store.setError(
        new Error(
          "Port conflicts not resolved. Please free the ports and try again.",
        ),
      );
      return null;
    }

    for (const result of portResults) {
      if (!result.available && result.alternative) {
        portOverrides[result.port] = result.alternative;
      }
    }
  }

  store.updateData("portOverrides", portOverrides);
  store.setStatus("Prerequisites check complete!");
  await delay(1000);

  return portOverrides;
}

/**
 * Runs mise trust + install + setup for developer mode.
 * Returns true on success, false on failure (store error is set).
 */
export async function runMiseDeveloperSetup(
  store: CLIStore,
  repoPath: string,
  portOverrides: Record<number, number>,
  logHandler: (chunk: string) => void,
): Promise<boolean> {
  store.setStep("Project Setup");
  store.updateData("dependencyPhase", "Setting up project...");
  store.updateData("dependencyProgress", 0);
  store.updateData("dependencyComplete", false);
  store.updateData("dependencyLogs", []);

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
    const dockerEnv =
      Object.keys(portOverrides).length > 0
        ? portOverridesToDockerEnv(portOverrides)
        : undefined;

    await runCommand(
      "mise",
      ["setup"],
      repoPath,
      (progress) => {
        store.updateData("dependencyProgress", 50 + progress * 0.5);
      },
      logHandler,
      dockerEnv,
    );

    store.updateData("dependencyProgress", 100);
    store.updateData("dependencyPhase", "Setup complete!");
    store.updateData("dependencyComplete", true);
    return true;
  } catch (e) {
    store.setError(
      new Error(`Failed to setup project: ${(e as Error).message}`),
    );
    return false;
  }
}
