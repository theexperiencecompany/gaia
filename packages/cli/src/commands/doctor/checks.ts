/**
 * Doctor checks — ordered diagnostics for a GAIA installation.
 *
 * Every check resolves to a {@link CheckResult}; a result is either ok, or
 * failed/skipped with a remediation hint. The command exits non-zero only when
 * a `severity: "blocker"` check fails — setup-readiness findings are warnings.
 *
 * @module commands/doctor/checks
 */

import {
  type ComposeContainerInfo,
  getComposeProjectContainers,
  getDiskFreeKb,
  getDockerRootDir,
  isDockerRunning,
} from "../../lib/docker.js";
import type { SetupMode } from "../../lib/env-parser.js";
import type { CheckResult } from "./types";

/** How a failed check influences the exit code. */

/** Minimum free space (bytes) required on the Docker data root. */
export const MIN_DISK_HEADROOM_BYTES = 2 * 1024 * 1024 * 1024;

const HTTP_TIMEOUT_MS = 5000;

// ---------------------------------------------------------------------------
// Compose project / expected services
// ---------------------------------------------------------------------------

/** Docker Compose project name for each detected setup mode. */
export const COMPOSE_PROJECT_BY_MODE: Record<SetupMode, ComposeProject> = {
  selfhost: "gaia-selfhost",
  developer: "gaia-dev",
};

export type ComposeProject = "gaia-selfhost" | "gaia-dev";

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
// Setup readiness (/api/v1/setup/status)
// ---------------------------------------------------------------------------

/** Subset of the public `/setup/status` payload the CLI cares about. */
export interface SetupStatusPayload {
  /** Instance auth tier: "local" marks a self-host install. */
  auth_mode?: "workos" | "local";
  models_seeded?: boolean;
  plans_seeded?: boolean;
  has_admin_account?: boolean;
  billing_enabled?: boolean;
  providers?: Record<string, { configured?: boolean }>;
}

export interface SetupReadinessItem {
  /** e.g. "models seeded". */
  label: string;
  configured: boolean;
  fix: string;
}

/** Maps an unconfigured readiness flag to its remediation hint. */
function readinessFix(webPort: number): string {
  return `Open http://localhost:${webPort}/setup in your browser and complete first-run setup.`;
}

export function evaluateSetupReadiness(
  payload: SetupStatusPayload,
  webPort: number,
): SetupReadinessItem[] {
  const anyProviderConfigured = Object.values(payload.providers ?? {}).some(
    (p) => p.configured === true,
  );

  const items: Array<{ label: string; configured: boolean }> = [
    { label: "models seeded", configured: payload.models_seeded === true },
    { label: "plans seeded", configured: payload.plans_seeded === true },
    { label: "LLM provider configured", configured: anyProviderConfigured },
    {
      label: "admin account created",
      configured: payload.has_admin_account === true,
    },
  ];

  // Billing is a hosted-tier concern: the backend pins billing_enabled to
  // ENV !== "selfhost" and self-host seeds the Free plan unconditionally, so
  // a local-auth instance can never satisfy this item and would warn forever.
  // AUTH_MODE=local is the payload's self-host marker (the backend refuses to
  // boot local auth outside selfhost/dev, and `gaia setup` provisions it for
  // every selfhost install). Unknown/absent auth_mode keeps the hosted
  // behavior — warning on unconfigured billing is the safe default there.
  if (payload.auth_mode !== "local") {
    items.push({
      label: "billing enabled",
      configured: payload.billing_enabled === true,
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

export async function checkDockerDaemon(): Promise<CheckResult> {
  const running = await isDockerRunning();
  return running
    ? {
        id: "docker-daemon",
        label: "Docker daemon",
        severity: "blocker",
        state: "ok",
      }
    : {
        id: "docker-daemon",
        label: "Docker daemon",
        severity: "blocker",
        state: "fail",
        detail: "'docker info' failed — daemon unreachable",
        fix: "Start OrbStack or Docker Desktop (macOS/Windows), or run: sudo systemctl start docker.",
      };
}

export async function checkComposeContainers(options: {
  project: string;
  expected: readonly string[];
}): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "compose-containers",
    label: `Compose containers (${options.project})`,
    severity: "blocker",
  };

  let containers: ComposeContainerInfo[];
  try {
    containers = await getComposeProjectContainers(options.project);
  } catch {
    return {
      ...base,
      state: "skipped",
      detail: "Docker daemon unreachable",
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

async function fetchWithTimeout(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  return fetch(url, { ...init, signal: AbortSignal.timeout(HTTP_TIMEOUT_MS) });
}

export async function checkApiHealth(apiPort: number): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "api-health",
    label: `API health (localhost:${apiPort})`,
    severity: "blocker",
  };

  try {
    const res = await fetchWithTimeout(`http://localhost:${apiPort}/health`);
    if (res.ok) {
      return { ...base, state: "ok", detail: `HTTP ${res.status}` };
    }
    return {
      ...base,
      state: "fail",
      detail: `HTTP ${res.status} from /health`,
      fix: "Check API logs: 'gaia logs', or restart the stack with 'gaia start'.",
    };
  } catch {
    return {
      ...base,
      state: "fail",
      detail: "Connection failed",
      fix: "Start the stack with 'gaia start' (self-host) or 'gaia dev' (developer mode).",
    };
  }
}

export async function checkWebReachable(webPort: number): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "web-reachable",
    label: `Web (localhost:${webPort})`,
    severity: "blocker",
  };

  try {
    const res = await fetchWithTimeout(`http://localhost:${webPort}`, {
      method: "HEAD",
    });
    if (res.ok) {
      return { ...base, state: "ok", detail: `HTTP ${res.status}` };
    }
    return {
      ...base,
      state: "fail",
      detail: `HTTP ${res.status} from /`,
      fix: "Check web logs: 'gaia logs', or restart the stack with 'gaia start'.",
    };
  } catch {
    return {
      ...base,
      state: "fail",
      detail: "Connection failed",
      fix: "Start the stack with 'gaia start' (self-host) or 'gaia dev' (developer mode).",
    };
  }
}

/**
 * Setup readiness — one warning-level result per unconfigured item. Skipped
 * when the API did not answer (the API health failure already explains why).
 */
export async function checkSetupReadiness(options: {
  apiHealthy: boolean;
  apiPort: number;
  webPort: number;
}): Promise<CheckResult[]> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "setup-readiness",
    label: "Setup readiness",
    severity: "warning",
  };

  if (!options.apiHealthy) {
    return [{ ...base, state: "skipped", detail: "API unreachable" }];
  }

  let payload: SetupStatusPayload;
  try {
    const res = await fetchWithTimeout(
      `http://localhost:${options.apiPort}/api/v1/setup/status`,
    );
    if (!res.ok) {
      return [
        {
          ...base,
          state: "skipped",
          detail: `HTTP ${res.status} from /api/v1/setup/status`,
        },
      ];
    }
    payload = (await res.json()) as SetupStatusPayload;
  } catch {
    return [
      { ...base, state: "skipped", detail: "Could not read setup status" },
    ];
  }

  const items = evaluateSetupReadiness(payload, options.webPort);

  if (items.every((item) => item.configured)) {
    return [{ ...base, state: "ok", detail: "All setup items configured" }];
  }

  return items
    .filter((item) => !item.configured)
    .map((item) => ({
      ...base,
      label: `Setup readiness: ${item.label}`,
      state: "fail" as const,
      detail: `${item.label.charAt(0).toUpperCase()}${item.label.slice(1)} is not configured`,
      fix: item.fix,
    }));
}

export async function checkDiskHeadroom(
  minimumBytes: number = MIN_DISK_HEADROOM_BYTES,
): Promise<CheckResult> {
  const base: Pick<CheckResult, "id" | "label" | "severity"> = {
    id: "disk-headroom",
    label: "Disk headroom",
    severity: "blocker",
  };

  let rootDir: string;
  try {
    rootDir = await getDockerRootDir();
  } catch {
    return { ...base, state: "skipped", detail: "Docker daemon unreachable" };
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
