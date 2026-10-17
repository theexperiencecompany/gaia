import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import {
  findInstallRoot,
  type StopServicesOptions,
  stopServices,
} from "../../lib/service-starter.js";
import type { CLIStore } from "../../ui/store.js";

export async function runStopFlow(
  store: CLIStore,
  options?: StopServicesOptions,
): Promise<void> {
  store.setStep("Stopping");
  store.setStatus("Finding your GAIA install…");

  const repoPath = findInstallRoot();
  if (!repoPath) {
    store.setError(
      new Error("GAIA isn't installed here, so there is nothing to stop."),
    );
    return;
  }

  store.updateData("repoPath", repoPath);
  store.updateData("stopMode", options?.forcePorts ? "force-ports" : "safe");
  const portOverrides = readDockerComposePortOverrides(repoPath);

  try {
    await stopServices(
      repoPath,
      (status) => store.setStatus(status),
      portOverrides,
      options,
    );
  } catch (e) {
    store.setError(new Error(`GAIA didn't stop. ${(e as Error).message}`));
    return;
  }
  store.setStep("Stopped");
  store.setStatus("GAIA stopped. Start it again with 'gaia start'.");
  store.updateData("stopped", true);
}
