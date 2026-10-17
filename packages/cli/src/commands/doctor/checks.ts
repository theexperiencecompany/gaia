/**
 * Doctor checks — ordered diagnostics for a GAIA installation.
 *
 * Every check resolves to a {@link CheckResult}; a result is either ok, or
 * failed/skipped with a remediation hint. The command exits non-zero only when
 * a `severity: "blocker"` check fails — setup-readiness findings are warnings.
 *
 * @module commands/doctor/checks
 */

import * as fs from "node:fs";
import * as os from "node:os";
import { execa } from "execa";
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
  getDiskFreeKb,
  getDockerRootDir,
} from "../../lib/docker.js";
import {
  type DockerAccess,
  describeDockerProblem,
  GAIA_UP_INSTALLS,
} from "../../lib/docker-access.js";
import type { SetupMode } from "../../lib/env-parser.js";
import { readPinnedGaiaVersion } from "../../lib/env-writer.js";
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

/** How a failed check influences the exit code. */

/** Minimum free space (bytes) required on the Docker data root. */
export const MIN_DISK_HEADROOM_BYTES = 2 * 1024 * 1024 * 1024;

/** Memory thresholds for the headroom check (bytes). */
export const MIN_MEMORY_WARN_BYTES = 4 * 1024 * 1024 * 1024;
export const MIN_MEMORY_FAIL_BYTES = 2 * 1024 * 1024 * 1024;

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

/** Host port with override support (`infra/docker/.env` → default). */
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
 * Re-checks the mode's host ports (respecting `infra/docker/.env` overrides)
 * for conflicts with non-GAIA processes; ports GAIA's own stack publishes are
 * not conflicts. Skipped when the Docker daemon is unreachable because the
 * check needs `docker ps` and `lsof`.
 */
export async function checkPortConflicts(
  mode: SetupMode,
  overrides: Record<number, number> = {},
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "port-conflict",
    label: "Ports",
    severity: "blocker",
  };

  let results: Awaited<ReturnType<typeof checkModePorts>>;
  try {
    results = await checkModePorts(mode, overrides);
  } catch {
    return {
      ...base,
      state: "skipped",
      detail: "Could not check ports",
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

  return {
    ...base,
    state: "fail",
    detail,
    fix:
      mode === "selfhost"
        ? "Free the port or re-run 'gaia up' with --web-port (or set WEB_HOST_PORT in infra/docker/.env)."
        : "Free the port or set its *_HOST_PORT override in infra/docker/.env.",
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
function readinessFix(webPort: number): string {
  return `Open http://localhost:${webPort}/setup in your browser to finish setting GAIA up.`;
}

/** llmProviderKeys is the catalog's chat-capable set — the one the server's _needs_setup counts. */
export function evaluateSetupReadiness(
  payload: SetupStatusPayload,
  llmProviderKeys: readonly string[],
  webPort: number,
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
    fix: item.configured ? "" : readinessFix(webPort),
  }));
}

// ---------------------------------------------------------------------------
// Disk headroom
// ---------------------------------------------------------------------------

/**
 * Available bytes from `df -k` output (last data line, 4th column:
 * 1K-blocks available).
 */
export function parseDfAvailableKb(stdout: string): number | null {
  const lines = stdout
    .trim()
    .split("\n")
    .filter((line) => line.trim().length > 0);
  const last = lines.at(-1);
  if (!last) return null;
  const columns = last.trim().split(/\s+/);
  const kb = Number(columns[3]);
  if (!Number.isFinite(kb) || kb < 0) return null;
  return kb;
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
  webPort: number;
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
    options.webPort,
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

export async function checkDiskHeadroom(
  minimumBytes: number = MIN_DISK_HEADROOM_BYTES,
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "disk-headroom",
    label: "Disk space",
    severity: "blocker",
  };

  let rootDir: string;
  try {
    rootDir = await getDockerRootDir();
  } catch {
    return { ...base, state: "skipped", detail: "they need Docker" };
  }

  let availableBytes: number | null;
  try {
    const dfOutput = await getDiskFreeKb(rootDir);
    const kb = parseDfAvailableKb(dfOutput);
    availableBytes = kb === null ? null : kb * 1024;
  } catch {
    availableBytes = null;
  }

  if (availableBytes === null) {
    return {
      ...base,
      state: "skipped",
      detail: `Could not read disk usage for ${rootDir}`,
    };
  }

  const gb = (bytes: number): string => `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (availableBytes >= minimumBytes) {
    return {
      ...base,
      state: "ok",
      detail: `${gb(availableBytes)} free at ${rootDir}`,
    };
  }

  return {
    ...base,
    state: "fail",
    detail: `${gb(availableBytes)} free at ${rootDir}, need ≥ ${gb(minimumBytes)}`,
    fix: "Free up disk space (e.g. 'docker system prune') before pulling/building images.",
  };
}

// ---------------------------------------------------------------------------
// Memory headroom
// ---------------------------------------------------------------------------

/**
 * Parse available bytes from `/proc/meminfo` content.
 * Prefers `MemAvailable`; falls back to `MemTotal` when `MemAvailable` is absent
 * (older kernels). Values are in kB.
 */
export function parseMemInfoAvailableBytes(content: string): number | null {
  const availableMatch = content.match(/^MemAvailable:\s+(\d+)\s+kB/m);
  if (availableMatch?.[1]) {
    const kb = Number(availableMatch[1]);
    if (Number.isFinite(kb) && kb >= 0) return kb * 1024;
  }
  const totalMatch = content.match(/^MemTotal:\s+(\d+)\s+kB/m);
  if (totalMatch?.[1]) {
    const kb = Number(totalMatch[1]);
    if (Number.isFinite(kb) && kb >= 0) return kb * 1024;
  }
  return null;
}

/** Approximate available bytes from `vm_stat` output as free + inactive + speculative pages. */
function parseVmStatAvailableBytes(stdout: string): number | null {
  // vm_stat header: "Mach Virtual Memory Statistics: (page size of 16384 bytes)"
  const pageSizeMatch = stdout.match(/page size of (\d+) bytes/);
  const pageSize = pageSizeMatch?.[1] ? Number(pageSizeMatch[1]) : 4096;
  const freeMatch = stdout.match(/Pages free:\s+(\d+)/);
  const inactiveMatch = stdout.match(/Pages inactive:\s+(\d+)/);
  const speculativeMatch = stdout.match(/Pages speculative:\s+(\d+)/);
  if (!(freeMatch || inactiveMatch || speculativeMatch)) return null;
  const pages = (match: RegExpMatchArray | null): number =>
    match ? Number(match[1]) : 0;
  const free = pages(freeMatch);
  const inactive = pages(inactiveMatch);
  if (
    !Number.isFinite(free) ||
    !Number.isFinite(inactive) ||
    !Number.isFinite(pageSize) ||
    pageSize <= 0
  ) {
    return null;
  }
  return (free + inactive + pages(speculativeMatch)) * pageSize;
}

function readOsMemory(read: () => number): number | null {
  try {
    return read();
  } catch {
    return null;
  }
}

function getLinuxAvailableMemoryBytes(): number | null {
  try {
    const content = fs.readFileSync("/proc/meminfo", "utf-8");
    const parsed = parseMemInfoAvailableBytes(content);
    if (parsed !== null) return parsed;
  } catch {
    // fall through to os.freemem fallback
  }
  return readOsMemory(() => os.freemem());
}

async function getDarwinAvailableMemoryBytes(): Promise<number | null> {
  try {
    const { stdout } = await execa("vm_stat", []);
    const parsed = parseVmStatAvailableBytes(stdout);
    if (parsed !== null) return parsed;
  } catch {
    // fall through to sysctl
  }
  try {
    const { stdout } = await execa("sysctl", ["-n", "hw.memsize"]);
    const total = Number(stdout.trim());
    if (Number.isFinite(total) && total > 0) return total;
  } catch {
    // fall through to os.totalmem
  }
  return readOsMemory(() => os.totalmem());
}

async function getAvailableMemoryBytes(): Promise<number | null> {
  const platform = os.platform();
  if (platform === "linux") return getLinuxAvailableMemoryBytes();
  if (platform === "darwin") return getDarwinAvailableMemoryBytes();
  return readOsMemory(() => os.freemem());
}

export async function checkMemoryHeadroom(): Promise<CheckResult> {
  const availableBytes = await getAvailableMemoryBytes().catch(() => null);

  if (availableBytes === null) {
    return {
      id: "memory-headroom",
      label: "Memory",
      severity: "blocker",
      state: "skipped",
      detail: "Could not read available memory",
    };
  }

  const gb = (bytes: number): string => `${(bytes / 1024 ** 3).toFixed(1)} GB`;

  if (availableBytes < MIN_MEMORY_FAIL_BYTES) {
    return {
      id: "memory-headroom",
      label: "Memory",
      severity: "blocker",
      state: "fail",
      detail: `${gb(availableBytes)} free; GAIA needs at least 2 GB to start`,
      fix: "Close other apps or add RAM before starting GAIA.",
    };
  }

  if (availableBytes < MIN_MEMORY_WARN_BYTES) {
    return {
      id: "memory-headroom",
      label: "Memory",
      severity: "warning",
      state: "fail",
      detail: `${gb(availableBytes)} free; GAIA's API uses about 2.5 GB and may run out during chats`,
      fix: "Close other apps or add RAM.",
    };
  }

  return {
    id: "memory-headroom",
    label: "Memory",
    severity: "blocker",
    state: "ok",
    detail: `${gb(availableBytes)} free`,
  };
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
