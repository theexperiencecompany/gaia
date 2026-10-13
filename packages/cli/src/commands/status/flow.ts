import { fetchDependencyReadiness } from "../../lib/dependency-readiness.js";
import { COMPOSE_PROJECT_BY_MODE } from "../../lib/docker.js";
import { localOrigin } from "../../lib/endpoints.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { checkAllServices, getDockerStatus } from "../../lib/healthcheck.js";
import {
  describeInstall,
  detectSetupMode,
  findInstallRoot,
} from "../../lib/service-starter.js";
import type { CLIStore } from "../../ui/store.js";

export async function runStatusChecks(store: CLIStore): Promise<void> {
  store.setStep("Checking");
  store.setStatus("Checking service health...");
  store.updateData("refreshable", false);

  const repoPath = findInstallRoot();
  const portOverrides = repoPath
    ? readDockerComposePortOverrides(repoPath)
    : undefined;
  const detectedMode = repoPath ? await detectSetupMode(repoPath) : null;
  store.updateData("install", describeInstall(repoPath, detectedMode));
  const mode = detectedMode ?? "developer";

  const [services, docker, readiness] = await Promise.all([
    checkAllServices(mode, portOverrides),
    getDockerStatus(mode),
    fetchDependencyReadiness(
      localOrigin(mode, portOverrides ?? {}),
      COMPOSE_PROJECT_BY_MODE[mode],
    ),
  ]);

  store.updateData("services", services);
  store.updateData("docker", docker);
  store.updateData("readiness", readiness);

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
