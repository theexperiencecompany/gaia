import { dockerAccessError, getDockerAccess } from "../../lib/docker-access.js";
import { DEFAULT_WEB_PORT, primaryWebUrl } from "../../lib/endpoints.js";
import {
  readDockerComposePortOverrides,
  readGaiaDomain,
} from "../../lib/env-writer.js";
import {
  detectSetupMode,
  findInstallRoot,
  type StartServicesOptions,
  startServices,
} from "../../lib/service-starter.js";
import { LOG_BUFFER_LINES } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";

export async function runStartFlow(
  store: CLIStore,
  options?: StartServicesOptions,
): Promise<void> {
  store.setStep("Starting");
  store.setStatus("Locating GAIA repository...");

  const repoPath = findInstallRoot();
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
    const access = await getDockerAccess();
    if (access !== "ready") {
      store.setError(await dockerAccessError(access));
      return;
    }
  }

  const portOverrides = readDockerComposePortOverrides(repoPath);
  const webPort = portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;

  store.updateData("setupMode", mode);
  store.updateData("webUrl", primaryWebUrl(webPort, readGaiaDomain(repoPath)));
  store.updateData("dockerLogs", []);
  store.setStatus("Starting GAIA...");

  try {
    await startServices(
      repoPath,
      mode,
      (status) => store.setStatus(status),
      portOverrides,
      (phase, finished) => {
        store.setStatus(phase.label);
        store.updateData("dockerLogs", finished.slice(-LOG_BUFFER_LINES));
      },
      options,
    );
  } catch (e) {
    store.setError(new Error(`GAIA didn't start. ${(e as Error).message}`));
    return;
  }
  store.setStep("Running");
  store.setStatus("GAIA is running.");
  store.updateData("started", true);
}
