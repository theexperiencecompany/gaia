import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { checkAllServices, getDockerStatus } from "../../lib/healthcheck.js";
import { findRepoRoot } from "../../lib/service-starter.js";
import type { CLIStore } from "../../ui/store.js";

export async function runStatusChecks(store: CLIStore): Promise<void> {
  store.setStep("Checking");
  store.setStatus("Checking service health...");
  store.updateData("refreshable", false);

  const repoPath = findRepoRoot();
  const portOverrides = repoPath
    ? readDockerComposePortOverrides(repoPath)
    : undefined;

  const [services, docker] = await Promise.all([
    checkAllServices(portOverrides),
    getDockerStatus(),
  ]);

  store.updateData("services", services);
  store.updateData("docker", docker);

  const upCount = services.filter((s) => s.status === "up").length;
  const totalCount = services.length;

  store.setStep("Results");
  store.setStatus(`${upCount}/${totalCount} services running`);
  store.updateData("refreshable", true);
}

export async function runStatusFlow(store: CLIStore): Promise<void> {
  while (true) {
    await runStatusChecks(store);

    const action = (await store.waitForInput("exit_or_refresh")) as
      | "exit"
      | "refresh";

    if (action !== "refresh") {
      break;
    }
  }
}
