import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { writeConfig } from "../../lib/config.js";
import { runEnvSetup, selectSetupMode } from "../../lib/env-setup.js";
import { portOverridesToDockerEnv } from "../../lib/env-writer.js";
import {
  createLogHandler,
  delay,
  runBasePrerequisiteChecks,
  runDeveloperPrerequisiteChecks,
  runPortChecks,
} from "../../lib/flow-utils.js";
import * as git from "../../lib/git.js";
import {
  findRepoRoot,
  runCommand,
  startServices,
} from "../../lib/service-starter.js";
import { CLI_VERSION } from "../../lib/version.js";
import { LOG_BUFFER_LINES } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";

const DEV_MODE = process.env.GAIA_CLI_DEV === "true";
const ANSI_ESCAPE_RE = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g");

export async function runInitFlow(
  store: CLIStore,
  branch?: string,
): Promise<void> {
  // 0. Welcome
  store.setStep("Welcome");
  store.setStatus("Waiting for user input...");
  await store.waitForInput("welcome");

  const logHandler = createLogHandler(store);

  // 1. Prerequisites
  store.setStep("Prerequisites");
  store.setStatus("Checking system requirements...");

  if (!(await runBasePrerequisiteChecks(store))) return;

  // Check Ports
  // Note: 8083 (Mongo Express) is only used in dev mode, but we check it here
  // since mode selection happens later in the flow.
  const portOverrides = await runPortChecks(store);
  if (portOverrides === null) return;

  // 2. Setup Mode
  const setupMode = await selectSetupMode(store);

  if (setupMode === "developer") {
    const developerPrereqs = await runDeveloperPrerequisiteChecks(store);
    if (!developerPrereqs) return;
  }

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
    store.setStep("Repository Setup");
    const defaultPath =
      setupMode === "selfhost"
        ? path.join(os.homedir(), "gaia")
        : path.resolve("gaia");

    let cloneFresh = true;
    repoPath = defaultPath;

    while (true) {
      repoPath = (await store.waitForInput("repo_path", {
        default: defaultPath,
      })) as string;

      // Resolve relative paths
      if (!path.isAbsolute(repoPath)) {
        repoPath = path.resolve(repoPath);
      }

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

        // Check if it's already a gaia repo
        const isGaiaRepo = fs.existsSync(
          path.join(repoPath, "apps/api/app/config/settings_validator.py"),
        );

        if (isGaiaRepo) {
          store.updateData("existingRepoPath", repoPath);
          const action = (await store.waitForInput("existing_repo")) as string;

          if (action === "use_existing") {
            cloneFresh = false;
            break;
          } else if (action === "delete_reclone") {
            store.setStatus("Removing existing installation...");
            try {
              fs.rmSync(repoPath, { recursive: true, force: true });
            } catch (e) {
              store.setError(
                new Error(
                  `Failed to remove directory: ${(e as Error).message}\nTry removing it manually: rm -rf "${repoPath}"`,
                ),
              );
              return;
            }
            break;
          } else if (action === "different_path") {
            continue;
          } else {
            // exit
            store.setError(new Error("Setup cancelled by user."));
            return;
          }
        }

        // Non-empty directory that isn't a gaia repo
        const files = fs.readdirSync(repoPath);
        if (files.length > 0) {
          store.setError(
            new Error(
              `Directory ${repoPath} is not empty and is not a GAIA installation. Please choose another path.`,
            ),
          );
          await delay(2000);
          store.setError(null);
          continue;
        }
      }
      break;
    }

    if (cloneFresh) {
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
              store.setStatus(
                `Cloning repository to ${repoPath}... ${progress}%`,
              );
            }
          },
          branch,
        );
        store.setStatus("Repository ready!");
      } catch (e) {
        store.setError(e as Error);
        return;
      }
    } else {
      store.setStatus("Using existing repository!");
    }
  }

  await delay(1000);

  // 3. Environment Setup (moved before tool install so we know the mode)
  await runEnvSetup(store, repoPath, setupMode, portOverrides);

  if (store.currentState.error) {
    return; // Abort if env setup failed
  }

  if (setupMode === "selfhost") {
    // Build and start services automatically on first init
    store.setStep("Project Setup");
    store.setStatus("Building and starting all services in Docker...");
    store.updateData(
      "dependencyPhase",
      "Building and starting Docker services...",
    );
    store.updateData("dependencyProgress", 0);
    store.updateData("dependencyLogs", []);
    store.updateData("dependencyComplete", false);

    const dockerLogHandler = (chunk: string) => {
      const lines = chunk
        .split("\n")
        .map((l: string) => l.replace(ANSI_ESCAPE_RE, "").trim())
        .filter((l: string) => l.length > 0);
      if (lines.length === 0) return;
      const current: string[] = store.currentState.data.dependencyLogs || [];
      store.updateData(
        "dependencyLogs",
        [...current, ...lines].slice(-LOG_BUFFER_LINES),
      );
    };

    // Try to pull pre-built images from GHCR first (fast path for self-hosters).
    // Fall back to building locally if pull fails (e.g. first release, no auth).
    let pullSucceeded = false;
    try {
      store.setStatus("Pulling pre-built images from registry...");
      await startServices(
        repoPath,
        "selfhost",
        (status) => store.setStatus(status),
        portOverrides,
        dockerLogHandler,
        { pull: true },
      );
      pullSucceeded = true;
    } catch (e) {
      const reason = (e as Error).message?.split("\n")[0] ?? "unknown error";
      store.setStatus(
        `Registry pull failed (${reason}) — building images locally (this takes a few minutes)...`,
      );
    }

    if (!pullSucceeded) {
      try {
        await startServices(
          repoPath,
          "selfhost",
          (status) => store.setStatus(status),
          portOverrides,
          dockerLogHandler,
          { build: true },
        );
      } catch (e) {
        store.setError(
          new Error(`Failed to start services: ${(e as Error).message}`),
        );
        return;
      }
    }

    store.updateData("dependencyProgress", 100);
    store.updateData("dependencyComplete", true);

    const envMethod = (store.currentState.data.envMethod as string) || "manual";
    writeConfig({
      version: CLI_VERSION,
      setupComplete: true,
      setupMethod: envMethod as "manual" | "infisical",
      repoPath,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    store.updateData("setupMode", setupMode);
    store.setStep("Finished");
    store.setStatus("Setup complete! GAIA is running.");
    await store.waitForInput("exit");
    return;
  }

  // 4. Install Tools (developer mode only)
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

  // 5. Project Setup (developer mode only)
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

    const dockerEnv =
      Object.keys(portOverrides).length > 0
        ? portOverridesToDockerEnv(portOverrides)
        : undefined;

    await runCommand(
      "mise",
      ["setup"],
      repoPath,
      (progress) => {
        store.updateData("dependencyProgress", progress);
      },
      logHandler,
      dockerEnv,
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

  const envMethod = (store.currentState.data.envMethod as string) || "manual";
  writeConfig({
    version: CLI_VERSION,
    setupComplete: true,
    setupMethod: envMethod as "manual" | "infisical",
    repoPath,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });

  store.setStep("Finished");
  store.setStatus("Setup complete! Run 'gaia dev' to start development mode.");
  await store.waitForInput("exit");
}
