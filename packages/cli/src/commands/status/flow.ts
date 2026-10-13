import { fetchDependencyReadiness } from "../../lib/dependency-readiness.js";
import { COMPOSE_PROJECT_BY_MODE } from "../../lib/docker.js";
import { localOrigin } from "../../lib/endpoints.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import {
  checkDeveloperServices,
  getDockerStatus,
} from "../../lib/healthcheck.js";
import {
  describeInstall,
  detectSetupMode,
  findInstallRoot,
} from "../../lib/service-starter.js";
import type { CLIStore } from "../../ui/store.js";

/**
 * Self-host publishes only the proxy, so its health is the compose containers
 * plus /health/ready through the proxy; developer mode also probes the host
 * ports its services publish.
 */
export async function runStatusChecks(store: CLIStore): Promise<void> {
  store.setStep("Checking");
  store.setStatus("Checking service health...");
  store.updateData("refreshable", false);

  const repoPath = findInstallRoot();
  const mode = repoPath ? await detectSetupMode(repoPath) : null;
  const install = describeInstall(repoPath, mode);
  store.updateData("install", install);

  if (!repoPath || !mode) {
    store.updateData("services", []);
    store.setStep("Results");
    store.setStatus(`Nothing to check: ${install}`);
    store.updateData("refreshable", true);
    return;
  }

  const portOverrides = readDockerComposePortOverrides(repoPath);
  const [services, docker, readiness] = await Promise.all([
    mode === "developer" ? checkDeveloperServices(portOverrides) : [],
    getDockerStatus(mode),
    fetchDependencyReadiness(
      localOrigin(mode, portOverrides),
      COMPOSE_PROJECT_BY_MODE[mode],
    ),
  ]);

  store.updateData("services", services);
  store.updateData("docker", docker);
  store.updateData("readiness", readiness);

  store.setStep("Results");
  if (mode === "selfhost") {
    const running = docker.containers.filter(
      (c) => c.status === "running",
    ).length;
    store.setStatus(
      `${running}/${docker.containers.length} containers running`,
    );
  } else {
    const up = services.filter((s) => s.status === "up").length;
    store.setStatus(`${up}/${services.length} services running`);
  }
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
