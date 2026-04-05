import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import {
  checkDockerDetailed,
  PREREQUISITE_URLS,
} from "../../lib/prerequisites.js";
import {
  detectSetupMode,
  findRepoRoot,
  type StartServicesOptions,
  startServices,
} from "../../lib/service-starter.js";
import { LOG_BUFFER_LINES } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";

const ANSI_ESCAPE_RE = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g");

export async function runStartFlow(
  store: CLIStore,
  options?: StartServicesOptions,
): Promise<void> {
  store.setStep("Starting");
  store.setStatus("Locating GAIA repository...");

  const repoPath = findRepoRoot();
  if (!repoPath) {
    store.setError(
      new Error(
        "Could not find GAIA repository. Run from within a cloned gaia repo.",
      ),
    );
    return;
  }

  store.updateData("repoPath", repoPath);

  const mode = await detectSetupMode(repoPath);
  if (!mode) {
    store.setError(
      new Error(
        "No .env file found. Run 'gaia init' for fresh setup, or 'gaia setup' to configure an existing repo.",
      ),
    );
    return;
  }

  if (mode === "developer") {
    store.setError(
      new Error(
        "Developer mode runs in foreground. Use 'gaia dev' or 'gaia dev full' instead of 'gaia start'.",
      ),
    );
    return;
  }

  // Check prerequisites before starting
  if (mode === "selfhost") {
    store.setStatus("Checking Docker...");
    const dockerInfo = await checkDockerDetailed();
    if (!dockerInfo.working) {
      store.setError(
        new Error(
          dockerInfo.errorMessage ||
            `Docker is not running. Please start Docker and try again.\n  ${PREREQUISITE_URLS.docker}`,
        ),
      );
      return;
    }
  }

  const portOverrides = readDockerComposePortOverrides(repoPath);
  const webPort = portOverrides[3000] ?? 3000;
  const apiPort = portOverrides[8000] ?? 8000;

  store.updateData("setupMode", mode);
  store.updateData("webPort", webPort);
  store.updateData("apiPort", apiPort);
  store.updateData("dockerLogs", []);
  store.setStatus(`Starting GAIA in ${mode} mode...`);

  const logHandler = (chunk: string) => {
    const lines = chunk
      .split("\n")
      .map((l) => l.replace(ANSI_ESCAPE_RE, "").trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0) return;
    const current: string[] = store.currentState.data.dockerLogs || [];
    store.updateData(
      "dockerLogs",
      [...current, ...lines].slice(-LOG_BUFFER_LINES),
    );
  };

  try {
    await startServices(
      repoPath,
      mode,
      (status) => {
        store.setStatus(status);
      },
      portOverrides,
      logHandler,
      options,
    );

    store.setStep("Running");
    store.setStatus("GAIA is running!");
    store.updateData("started", true);
  } catch (e) {
    store.setError(
      new Error(`Failed to start services: ${(e as Error).message}`),
    );
    return;
  }

  await store.waitForInput("exit");
}
