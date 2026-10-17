import type { SetupStatusResponse } from "@gaia/shared/api/generated";
import { botService } from "../../lib/bots.js";
import { readConfig } from "../../lib/config.js";
import { fetchDependencyReadiness } from "../../lib/dependency-readiness.js";
import {
  COMPOSE_PROJECT_BY_MODE,
  type ContainerStatus,
} from "../../lib/docker.js";
import {
  DEFAULT_WEB_PORT,
  installWebUrl,
  localApiUrl,
  localOrigin,
} from "../../lib/endpoints.js";
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
import { readSetupEndpoint } from "../../lib/setup-endpoints.js";
import type { CLIStore } from "../../ui/store.js";
import type { StatusFacts } from "./report.js";

/** Store key holding the facts the status report is built from. */
export const STATUS_FACTS_KEY = "statusFacts";

/**
 * Self-host publishes only the proxy, so its health is the compose containers
 * plus /health/ready through the proxy; developer mode also probes the host
 * ports its services publish.
 */
async function collectFacts(): Promise<StatusFacts> {
  const repoPath = findInstallRoot();
  const mode = repoPath ? await detectSetupMode(repoPath) : null;
  const install = describeInstall(repoPath, mode);
  if (!repoPath || !mode) {
    return { install, installed: false, services: [], setupComplete: null };
  }

  const portOverrides = readDockerComposePortOverrides(repoPath);
  const webPort = portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  const [services, docker, readiness] = await Promise.all([
    mode === "developer" ? checkDeveloperServices(portOverrides) : [],
    getDockerStatus(mode),
    fetchDependencyReadiness(
      localOrigin(mode, portOverrides),
      COMPOSE_PROJECT_BY_MODE[mode],
    ),
  ]);
  const setup = readiness.reachable
    ? await readSetupEndpoint<SetupStatusResponse>(
        localApiUrl(mode, portOverrides),
        "status",
      )
    : null;

  return {
    install,
    installed: true,
    docker:
      mode === "selfhost" && docker.access === "ready"
        ? { ...docker, containers: withEnabledBots(docker.containers) }
        : docker,
    readiness,
    services,
    webUrl: installWebUrl(repoPath, webPort),
    setupComplete: setup && "data" in setup ? !setup.data.needs_setup : null,
  };
}

/** List every enabled chat bot, including one whose container was never created. */
function withEnabledBots(containers: ContainerStatus[]): ContainerStatus[] {
  const absent = (readConfig()?.bots ?? [])
    .map(botService)
    .filter((service) => !containers.some((c) => c.name === service));
  return [
    ...containers,
    ...absent.map((name): ContainerStatus => ({ name, status: "not_found" })),
  ];
}

export async function runStatusChecks(store: CLIStore): Promise<void> {
  store.setStep("Checking");
  store.setStatus("Checking GAIA's services…");
  const facts = await collectFacts();
  store.updateData(STATUS_FACTS_KEY, facts);
  store.updateData("checkedAt", new Date().toLocaleTimeString());
  store.setStep("Results");
}

/**
 * Check once and finish, like `docker ps`. With watch, keep the screen up:
 * r checks again, q / Esc / Enter leaves.
 */
export async function runStatusFlow(
  store: CLIStore,
  options: { watch?: boolean } = {},
): Promise<void> {
  store.updateData("watch", options.watch === true);
  for (;;) {
    await runStatusChecks(store);
    if (!options.watch) return;
    const action = await store.waitForInput("exit_or_refresh");
    if (action !== "refresh") return;
  }
}
