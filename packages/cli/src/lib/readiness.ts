/**
 * Post-start readiness gate for `gaia up`.
 *
 * Compose reporting "started" is not the same as services answering requests:
 * containers come up while migrations and first-boot init are still running,
 * so printing the success URL immediately lands the first browser click on
 * "connection refused". This module polls the API health endpoint and the web
 * app until they answer and is the only thing standing between startServices
 * and the "GAIA is running" box.
 *
 * Polling is concurrent: every round probes each target that has not answered
 * yet, answered targets drop out, and success is declared only when none
 * remain. On timeout the caller reports honestly which services were still
 * starting instead of claiming success.
 * @module commands/up/readiness
 */

import type { CLIStore } from "../ui/store.js";
import { delay } from "./flow-utils.js";

/** How often pending targets are re-probed. */
export const READINESS_INTERVAL_MS = 5_000;

/**
 * Total budget across all targets. First boots run database migrations and
 * seeding inside the containers after compose reports them up, which can take
 * minutes — but an unbounded wait is worse than an honest "still starting"
 * with a pointer at `gaia status`.
 */
export const READINESS_TIMEOUT_MS = 5 * 60_000;

/** Per-request cap so a hung socket cannot outlive the polling deadline. */
const PROBE_TIMEOUT_MS = 5_000;

export interface ReadinessTarget {
  /** Short name shown in progress output (e.g. "API"). */
  label: string;
  /** URL probed every round until it answers. */
  url: string;
  /**
   * When true the target counts as ready only on a 2xx response (health
   * endpoints). When false ANY HTTP response counts — for pages the point is
   * proving the server answers at all instead of refusing connections.
   */
  requireOk: boolean;
}

export type WaitForServicesResult =
  | { ready: true }
  | { ready: false; stillStarting: string };

export interface WaitForServicesOptions {
  timeoutMs?: number;
  intervalMs?: number;
  /** Called after every round that leaves targets unanswered. */
  onProgress?: (pendingLabels: readonly string[]) => void;
}

/**
 * Poll every target until all have answered or the timeout budget is spent.
 * @returns ready:true once every target answers; otherwise the labels still starting.
 */
export async function waitForServices(
  targets: readonly ReadinessTarget[],
  options: WaitForServicesOptions = {},
): Promise<WaitForServicesResult> {
  const intervalMs = options.intervalMs ?? READINESS_INTERVAL_MS;
  const deadline = Date.now() + (options.timeoutMs ?? READINESS_TIMEOUT_MS);

  const pending = new Map(
    targets.map((target) => [target.label, target] as const),
  );

  for (;;) {
    await Promise.all(
      [...pending.values()].map(async (target) => {
        if (await probe(target)) {
          pending.delete(target.label);
        }
      }),
    );
    if (pending.size === 0) {
      return { ready: true };
    }
    if (Date.now() >= deadline) {
      return { ready: false, stillStarting: [...pending.keys()].join(", ") };
    }
    options.onProgress?.([...pending.keys()]);
    await delay(intervalMs);
  }
}

async function probe(target: ReadinessTarget): Promise<boolean> {
  try {
    const res = await fetch(target.url, {
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    return target.requireOk ? res.ok : true;
  } catch {
    return false;
  }
}

/**
 * Readiness gate for the freshly started selfhost stack, wired to the up flow's
 * Project Setup UI: reuses its spinner phase to show which services are still
 * coming online while the loop polls.
 *
 * @returns WaitForServicesResult from the underlying wait loop; the flow turns
 * a timeout into an honest "still starting" finish screen (exit stays 0).
 */
export async function waitForUpReadiness(
  store: CLIStore,
  endpoints: { apiUrl: string; webPort: number },
): Promise<WaitForServicesResult> {
  const result = await waitForServices(
    [
      {
        label: "API",
        url: `${endpoints.apiUrl}/ping`,
        requireOk: true,
      },
      {
        label: "Web",
        url: `http://localhost:${endpoints.webPort}/login`,
        requireOk: false,
      },
    ],
    {
      onProgress: (pendingLabels) => {
        announceWait(store, pendingLabels);
      },
    },
  );

  store.updateData(
    "dependencyPhase",
    result.ready
      ? "GAIA is answering"
      : `Still starting: ${result.stillStarting}`,
  );
  store.updateData("dependencyComplete", true);

  return result;
}

function announceWait(store: CLIStore, pendingLabels: readonly string[]): void {
  const message = `Waiting for ${pendingLabels.join(" and ")} to come online…`;
  // The DependencyInstallStep spinner reads dependencyPhase; keep the footer
  // status in sync so both surfaces tell the same story.
  store.setStatus(message);
  store.updateData("dependencyComplete", false);
  store.updateData("dependencyPhase", message);
}
