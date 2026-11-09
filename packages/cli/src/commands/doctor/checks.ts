/**
 * Doctor checks — ordered diagnostics for a GAIA installation.
 *
 * Every check resolves to a {@link CheckResult}; a result is either ok, or
 * failed/skipped with a remediation hint. The command exits non-zero only when
 * a `severity: "blocker"` check fails — setup-readiness findings are warnings.
 *
 * @module commands/doctor/checks
 */

import { pinnedPorts } from "../../lib/answers.js";
import {
  botContainerState,
  botService,
  type SelfhostBot,
} from "../../lib/bots.js";
import { fetchDependencyReadiness } from "../../lib/dependency-readiness.js";
import { dependencyName, serviceName } from "../../lib/display-names.js";
import {
  type ComposeContainerInfo,
  type ComposeProject,
  getComposeProjectContainers,
} from "../../lib/docker.js";
import {
  type DockerAccess,
  describeDockerProblem,
  GAIA_UP_INSTALLS,
} from "../../lib/docker-access.js";
import type { SetupMode } from "../../lib/env-parser.js";
import { readPinnedGaiaVersion } from "../../lib/env-writer.js";
import {
  getDockerRootDir,
  judgeDisk,
  judgeMemory,
  readDockerDiskFree,
  readDockerMemoryBytes,
  thisMemoryHost,
} from "../../lib/host-resources.js";
import type {
  DiskPurpose,
  ResourceVerdict,
} from "../../lib/host-resources.types.js";
import { fixedPortError } from "../../lib/port-conflicts.js";
import { checkModePorts } from "../../lib/prerequisites.js";
import {
  fetchWithTimeout,
  readSetupEndpoint,
} from "../../lib/setup-endpoints.js";
import {
  displayTag,
  isNewerRelease,
  refreshLatestRelease,
  releaseVersion,
} from "../../lib/update-check.js";
import type { CheckResult } from "./types";

// ---------------------------------------------------------------------------
// Compose project / expected services
// ---------------------------------------------------------------------------

/**
 * Services that must be up per mode. Developer mode runs the app processes
 * via Nx (no gaia-backend/gaia-web containers), so only core infra is
 * expected. One-shot jobs like seed-models are intentionally excluded.
 */
export const EXPECTED_SERVICES: Record<ComposeProject, readonly string[]> = {
  "gaia-selfhost": [
    "chromadb",
    "postgres",
    "redis",
    "mongo",
    "rabbitmq",
    "gaia-backend",
    "gaia-web",
    "arq_worker",
    "proxy",
  ],
  "gaia-dev": ["chromadb", "postgres", "redis", "mongo", "rabbitmq"],
};

export function classifyContainerState(
  state: string,
): "running" | "restarting" | "stopped" {
  if (state === "running") return "running";
  if (state === "restarting") return "restarting";
  return "stopped";
}

/** True when every expected service is running. */
export function areServicesRunning(
  containers: ComposeContainerInfo[],
  expected: readonly string[],
): boolean {
  return expected.every((service) =>
    containers.some(
      (c) =>
        c.service === service && classifyContainerState(c.state) === "running",
    ),
  );
}

/** "postgres stopped, arq_worker restarting, mongo missing". */
export function describeUnhealthyServices(
  containers: ComposeContainerInfo[],
  expected: readonly string[],
): string {
  return expected
    .map((service) => ({
      service,
      info: containers.find((c) => c.service === service),
    }))
    .filter(
      ({ info }) => !info || classifyContainerState(info.state) !== "running",
    )
    .map(({ service, info }) =>
      info
        ? `${service} ${classifyContainerState(info.state)}`
        : `${service} missing`,
    )
    .join(", ");
}

// ---------------------------------------------------------------------------
// Ports
// ---------------------------------------------------------------------------

/** Host port with override support (the compose env file → default). */
export function resolvePort(
  overrides: Record<number, number>,
  defaultPort: number,
): number {
  return overrides[defaultPort] ?? defaultPort;
}

// ---------------------------------------------------------------------------
// Port conflicts (host ports required by GAIA, after overrides)
// ---------------------------------------------------------------------------

/**
 * Re-checks the mode's host ports (respecting the compose env file's overrides)
 * for conflicts with non-GAIA processes; ports GAIA's own stack publishes are
 * not conflicts. Skipped when the Docker daemon is unreachable because the
 * check needs `docker ps` and `lsof`.
 */
export async function checkPortConflicts(
  mode: SetupMode,
  overrides: Record<number, number> = {},
  domain?: string,
  /** The install's compose env file, as the user would type it; none without an install. */
  envFile?: string,
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "port-conflict",
    label: "Ports",
    severity: "blocker",
  };

  let results: Awaited<ReturnType<typeof checkModePorts>>;
  try {
    results = await checkModePorts(mode, overrides);
  } catch (e) {
    return {
      ...base,
      state: "skipped",
      detail: (e as Error).message,
    };
  }

  const conflicts = results.filter((r) => !r.available);
  if (conflicts.length === 0) {
    return {
      ...base,
      state: "ok",
      detail: "no conflicts",
    };
  }

  const detail = conflicts
    .map((c) => `:${c.port} in use by ${c.usedBy ?? "unknown"}`)
    .join(", ");

  // A domain's 80/443 can't move, so the fix is what gaia up says: stop the holder.
  const fixed = pinnedPorts({ domain }).fixed;
  const domainConflict = conflicts.find((c) => fixed[c.defaultPort]);
  if (domainConflict) {
    return {
      ...base,
      state: "fail",
      detail,
      fix: fixedPortError(domainConflict, "domain"),
    };
  }

  return {
    ...base,
    state: "fail",
    detail,
    fix:
      mode === "selfhost"
        ? `Free the port or re-run 'gaia up' with --web-port${envFile ? ` (or set WEB_HOST_PORT in ${envFile})` : ""}.`
        : `Free the port${envFile ? ` or set its *_HOST_PORT override in ${envFile}` : ""}.`,
  };
}

// ---------------------------------------------------------------------------
// Setup readiness (/api/v1/setup/status + /api/v1/setup/catalog)
// ---------------------------------------------------------------------------

import type {
  ProviderCatalogResponse,
  SetupStatusResponse,
} from "@gaia/shared/api/generated";

/** The public `/setup/status` payload, straight from the generated contract. */
export type SetupStatusPayload = SetupStatusResponse;

export interface SetupReadinessItem {
  /** e.g. "plans seeded". */
  label: string;
  configured: boolean;
  /** What doctor reports while the item is unconfigured, e.g. "no admin account yet". */
  missing: string;
  fix: string;
}

/** Maps an unconfigured readiness flag to its remediation hint. */
function readinessFix(webUrl: string): string {
  return `Open ${webUrl}/setup in your browser to finish setting GAIA up.`;
}

/** llmProviderKeys is the catalog's chat-capable set — the one the server's _needs_setup counts. */
export function evaluateSetupReadiness(
  payload: SetupStatusPayload,
  llmProviderKeys: readonly string[],
  webUrl: string,
): SetupReadinessItem[] {
  const llmConfigured = llmProviderKeys.some(
    (key) => payload.providers?.[key]?.configured === true,
  );

  const items: Omit<SetupReadinessItem, "fix">[] = [
    {
      label: "LLM provider configured",
      configured: llmConfigured,
      missing: "no AI provider yet",
    },
    {
      label: "admin account created",
      configured: payload.has_admin_account === true,
      missing: "no admin account yet",
    },
  ];

  // Plans exist only to be bought; an instance that does not bill has none.
  if (payload.deployment.bills) {
    items.push({
      label: "plans seeded",
      configured: payload.plans_seeded,
      missing: "billing plans not set up yet",
    });
  }

  return items.map((item) => ({
    ...item,
    fix: item.configured ? "" : readinessFix(webUrl),
  }));
}

// ---------------------------------------------------------------------------
// Checks
// ---------------------------------------------------------------------------

export async function checkDockerDaemon(
  access: DockerAccess,
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "docker-daemon",
    label: "Docker",
    severity: "blocker",
  };
  if (access === "ready") return { ...base, state: "ok", detail: "running" };
  const problem = await describeDockerProblem(access);
  return { ...base, state: "fail", detail: problem.state, fix: problem.fix };
}

export async function checkComposeContainers(options: {
  project: string;
  expected: readonly string[];
}): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "compose-containers",
    label: "Containers",
    severity: "blocker",
  };

  let containers: ComposeContainerInfo[];
  try {
    containers = await getComposeProjectContainers(options.project);
  } catch {
    return {
      ...base,
      state: "skipped",
      detail: "they need Docker",
    };
  }

  if (areServicesRunning(containers, options.expected)) {
    return {
      ...base,
      state: "ok",
      detail: `${options.expected.length} services running`,
    };
  }

  return {
    ...base,
    state: "fail",
    detail: describeUnhealthyServices(containers, options.expected),
    fix: `Run 'gaia start' to bring the stack up, or check 'docker compose -p ${options.project} logs'.`,
  };
}

/** The compose check's result when there is no configured install to inspect. */
export function unconfiguredInstallCheck(repoPath: string | null): CheckResult {
  const base: Pick<CheckResult, "id" | "label" | "severity" | "state"> = {
    id: "compose-containers",
    label: "GAIA",
    severity: "blocker",
    state: "fail",
  };
  if (!repoPath) {
    return {
      ...base,
      detail: "isn't installed yet",
      fix: GAIA_UP_INSTALLS,
    };
  }
  return {
    ...base,
    detail: `${repoPath} isn't set up yet (no apps/api/.env)`,
    fix: "Run 'gaia up' to finish setting it up, or 'gaia setup' for a development checkout.",
  };
}

/** startCommand is how this install starts: gaia start, or gaia dev for a developer checkout. */
export async function checkApiHealth(
  apiUrl: string,
  startCommand = "gaia start",
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "api-health",
    label: "API",
    severity: "blocker",
  };

  try {
    const res = await fetchWithTimeout(`${apiUrl}/ping`);
    if (res.ok) {
      return { ...base, state: "ok", detail: `answering at ${apiUrl}` };
    }
    return {
      ...base,
      state: "fail",
      detail: `answered HTTP ${res.status} at ${apiUrl}/ping`,
      fix: `See why with 'gaia logs', then restart it with '${startCommand}'.`,
    };
  } catch {
    return {
      ...base,
      state: "fail",
      detail: `not answering at ${apiUrl}`,
      fix: `Start GAIA with '${startCommand}'.`,
    };
  }
}

/**
 * One result per backing service from /health/ready. Skipped when the API did
 * not answer: the API health failure already explains why.
 */
export async function checkDependencies(options: {
  apiHealthy: boolean;
  origin: string;
  project: ComposeProject;
}): Promise<CheckResult[]> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "dependencies",
    label: "Dependencies",
    severity: "blocker",
  };
  if (!options.apiHealthy) {
    return [{ ...base, state: "skipped", detail: "they need GAIA's API" }];
  }
  const readiness = await fetchDependencyReadiness(
    options.origin,
    options.project,
  );
  if (!readiness.reachable) {
    return [
      {
        ...base,
        state: "fail",
        detail: readiness.detail,
        fix: "Run 'gaia update': an API or proxy older than this CLI does not serve /health/ready.",
      },
    ];
  }
  return readiness.dependencies.map((dependency) => ({
    id: `dependency-${dependency.name}`,
    label: dependencyName(dependency.name),
    severity: "blocker",
    state: dependency.ok ? "ok" : "fail",
    detail: dependency.ok
      ? `${Math.round(dependency.latency_ms)} ms`
      : `${dependency.error_type ?? "failed"} after ${Math.round(dependency.latency_ms)} ms`,
    fix: dependency.fix,
  }));
}

export async function checkWebReachable(
  webPort: number,
  startCommand = "gaia start",
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "web-reachable",
    label: "Web app",
    severity: "blocker",
  };

  try {
    const res = await fetchWithTimeout(`http://localhost:${webPort}`, {
      method: "HEAD",
    });
    if (res.ok) {
      return {
        ...base,
        state: "ok",
        detail: `answering at http://localhost:${webPort}`,
      };
    }
    return {
      ...base,
      state: "fail",
      detail: `answered HTTP ${res.status} at http://localhost:${webPort}`,
      fix: `See why with 'gaia logs', then restart it with '${startCommand}'.`,
    };
  } catch {
    return {
      ...base,
      state: "fail",
      detail: `not answering at http://localhost:${webPort}`,
      fix: `Start GAIA with '${startCommand}'.`,
    };
  }
}

/**
 * Setup readiness — one warning-level result per unconfigured item. Skipped
 * when the API did not answer (the API health failure already explains why).
 */
export async function checkSetupReadiness(options: {
  apiHealthy: boolean;
  apiUrl: string;
  /** The address the ready screen names, so the fix points the browser at the same place. */
  webUrl: string;
}): Promise<CheckResult[]> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "setup-readiness",
    label: "Setup",
    severity: "warning",
  };

  if (!options.apiHealthy) {
    return [{ ...base, state: "skipped", detail: "they need GAIA's API" }];
  }

  const [status, catalog] = await Promise.all([
    readSetupEndpoint<SetupStatusPayload>(options.apiUrl, "status"),
    readSetupEndpoint<ProviderCatalogResponse>(options.apiUrl, "catalog"),
  ]);
  if ("detail" in status) {
    return [{ ...base, state: "skipped", detail: status.detail }];
  }
  if ("detail" in catalog) {
    return [{ ...base, state: "skipped", detail: catalog.detail }];
  }

  const items = evaluateSetupReadiness(
    status.data,
    catalog.data.llm_provider_keys,
    options.webUrl,
  );

  if (items.every((item) => item.configured)) {
    return [{ ...base, state: "ok", detail: "finished" }];
  }

  // One row and one fix for everything the browser wizard still owes.
  const missing = items.filter((item) => !item.configured);
  return [
    {
      ...base,
      state: "fail",
      detail: `not finished: ${missing.map((item) => item.missing).join(", ")}`,
      fix: missing[0]?.fix,
    },
  ];
}

/** A resource verdict as a doctor row: too little blocks, tight only warns. */
function resourceCheck(
  base: Pick<CheckResult, "id" | "label">,
  verdict: ResourceVerdict,
): CheckResult {
  if (verdict.level === "ok") {
    return {
      ...base,
      severity: "blocker",
      state: "ok",
      detail: verdict.detail,
    };
  }
  return {
    ...base,
    severity: verdict.level === "fail" ? "blocker" : "warning",
    state: "fail",
    detail: verdict.detail,
    fix: verdict.fix,
  };
}

/** Free space on Docker's data root; "install" also counts the images a first run downloads. */
export async function checkDiskHeadroom(
  purpose: DiskPurpose,
): Promise<CheckResult> {
  const base = { id: "disk-headroom", label: "Disk space" };
  let rootDir: string;
  try {
    rootDir = await getDockerRootDir();
  } catch {
    return {
      ...base,
      severity: "blocker",
      state: "skipped",
      detail: "they need Docker",
    };
  }
  try {
    const free = await readDockerDiskFree(rootDir);
    if (free === null) {
      return {
        ...base,
        severity: "blocker",
        state: "skipped",
        detail: `Docker keeps ${rootDir} inside its own VM`,
      };
    }
    return resourceCheck(base, judgeDisk(free, rootDir, purpose));
  } catch (e) {
    return {
      ...base,
      severity: "blocker",
      state: "skipped",
      detail: (e as Error).message,
    };
  }
}

/** The memory Docker can give GAIA (its VM's on a Mac or WSL). */
export async function checkMemoryHeadroom(): Promise<CheckResult> {
  const base = { id: "memory-headroom", label: "Memory" };
  try {
    const total = await readDockerMemoryBytes();
    return resourceCheck(base, judgeMemory(total, thisMemoryHost()));
  } catch {
    return {
      ...base,
      severity: "blocker",
      state: "skipped",
      detail: "they need Docker",
    };
  }
}

/**
 * Warns only when a newer release is published for this computer; a
 * development build (latest, a commit) is never told to "update" backwards.
 */
export async function checkReleaseVersion(
  repoPath: string | null,
  mode: SetupMode | null,
  latestRelease: () => Promise<string | null> = refreshLatestRelease,
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "gaia-version",
    label: "GAIA version",
    severity: "warning",
  };
  if (!repoPath) {
    return { ...base, state: "skipped", detail: "GAIA isn't installed" };
  }
  if (mode !== "selfhost") {
    return {
      ...base,
      state: "skipped",
      detail: "Developer checkout: update it with 'gaia update --git'",
    };
  }
  const pinned = readPinnedGaiaVersion(repoPath);
  if (releaseVersion(pinned) === null) {
    return {
      ...base,
      state: "ok",
      detail: `development build (${displayTag(pinned)})`,
    };
  }
  const latest = await latestRelease();
  if (latest && isNewerRelease(latest, pinned)) {
    return {
      ...base,
      state: "fail",
      detail: `${latest} is available (this install runs ${pinned})`,
      fix: "Run 'gaia update'. Your data and settings are kept.",
    };
  }
  return { ...base, state: "ok", detail: pinned };
}

/** One result per enabled chat bot; a bot is optional, so a failure only warns. */
export async function checkBots(
  bots: readonly SelfhostBot[],
  project: ComposeProject,
): Promise<CheckResult[]> {
  if (bots.length === 0) return [];
  let containers: ComposeContainerInfo[] | null;
  try {
    containers = await getComposeProjectContainers(project);
  } catch {
    containers = null;
  }
  return bots.map((bot): CheckResult => {
    const base: Pick<CheckResult, "id" | "label" | "severity"> = {
      id: `bot-${bot}`,
      label: serviceName(botService(bot)),
      severity: "warning",
    };
    if (!containers) {
      return { ...base, state: "skipped", detail: "they need Docker" };
    }
    const { health, detail } = botContainerState(bot, containers);
    if (health !== "failing") return { ...base, state: "ok", detail };
    return {
      ...base,
      state: "fail",
      detail,
      fix: `A rejected or revoked token keeps the bot restarting: check 'docker compose -p ${project} logs ${botService(bot)}', then rerun 'gaia bots add ${bot}' with a fresh token.`,
    };
  });
}
