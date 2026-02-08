import type { CLIStore } from "../../ui/store.js";
import {
  startServices,
  detectSetupMode,
  findRepoRoot,
} from "../../lib/service-starter.js";

export async function runStartFlow(store: CLIStore): Promise<void> {
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
        "No .env file found. Run 'gaia setup' first to configure the environment.",
      ),
    );
    return;
  }

  store.updateData("setupMode", mode);
  store.setStatus(`Starting GAIA in ${mode} mode...`);

  try {
    await startServices(repoPath, mode, (status) => {
      store.setStatus(status);
    });

    store.setStep("Running");
    store.setStatus("GAIA is running!");
    store.updateData("started", true);
  } catch (e) {
    store.setError(
      new Error(`Failed to start services: ${(e as Error).message}`),
    );
  }
}
