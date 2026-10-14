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
    showResults(store, `Nothing to check: ${install}`);
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

  if (mode === "selfhost") {
    const running = docker.containers.filter(
      (c) => c.status === "running",
    ).length;
    showResults(
      store,
      `${running}/${docker.containers.length} containers running`,
    );
  } else {
    const up = services.filter((s) => s.status === "up").length;
    showResults(store, `${up}/${services.length} services running`);
  }
}

/** Publish a finished check: the summary, when it ran, and that r may refresh it. */
function showResults(store: CLIStore, summary: string): void {
  store.updateData("checkedAt", new Date().toLocaleTimeString());
  store.setStep("Results");
  store.setStatus(summary);
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
