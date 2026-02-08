import type { CLIStore } from "../../ui/store.js";
import { stopServices, findRepoRoot } from "../../lib/service-starter.js";

export async function runStopFlow(store: CLIStore): Promise<void> {
  store.setStep("Stopping");
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

  try {
    await stopServices(repoPath, (status) => {
      store.setStatus(status);
    });

    store.setStep("Stopped");
    store.setStatus("All services stopped.");
    store.updateData("stopped", true);
  } catch (e) {
    store.setError(
      new Error(`Failed to stop services: ${(e as Error).message}`),
    );
  }
}
