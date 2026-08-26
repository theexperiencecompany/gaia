/**
 * Doctor flow — runs all checks in order and collects the report.
 *
 * Order matters: later checks depend on earlier ones (containers and disk
 * headroom need the daemon, setup readiness needs a healthy API). Dependent
 * checks degrade to `skipped` — not failed — so one root cause doesn't spam
 * five failures.
 *
 * @module commands/doctor/flow
 */

import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { detectSetupMode, findRepoRoot } from "../../lib/service-starter.js";
import {
  COMPOSE_PROJECT_BY_MODE,
  type ComposeProject,
  checkApiHealth,
  checkComposeContainers,
  checkDiskHeadroom,
  checkDockerDaemon,
  checkSetupReadiness,
  checkWebReachable,
  EXPECTED_SERVICES,
  resolvePort,
} from "./checks.js";
import type { CheckResult } from "./types.js";

export interface DoctorReport {
  results: CheckResult[];
}

/**
 * Exit code contract: 1 only when a blocker failed; warnings never affect
 * the exit code.
 */
export function hasBlockingFailure(report: DoctorReport): boolean {
  return report.results.some(
    (result) => result.severity === "blocker" && result.state === "fail",
  );
}

/** Resolved context shared by the checks (host ports, compose project). */
interface DoctorContext {
  apiPort: number;
  webPort: number;
  /** Compose project name, or null when the setup mode is undetectable. */
  project: ComposeProject | null;
}

async function resolveContext(): Promise<DoctorContext> {
  const repoPath = findRepoRoot();
  const overrides = repoPath ? readDockerComposePortOverrides(repoPath) : {};
  const mode = repoPath ? await detectSetupMode(repoPath) : null;

  return {
    apiPort: resolvePort(overrides, 8000),
    webPort: resolvePort(overrides, 3000),
    project: mode ? COMPOSE_PROJECT_BY_MODE[mode] : null,
  };
}

export async function runDoctorChecks(): Promise<DoctorReport> {
  const results: CheckResult[] = [];
  const ctx = await resolveContext();

  // 1. Docker daemon reachable.
  results.push(await checkDockerDaemon());

  // 2. Compose project containers.
  if (!ctx.project) {
    results.push({
      id: "compose-containers",
      label: "Compose containers",
      severity: "blocker",
      state: "fail",
      detail: "Could not determine setup mode",
      fix: "Run 'gaia setup' to configure the repository first.",
    });
  } else {
    results.push(
      await checkComposeContainers({
        project: ctx.project,
        expected: EXPECTED_SERVICES[ctx.project],
      }),
    );
  }

  // 3. API health.
  const api = await checkApiHealth(ctx.apiPort);
  results.push(api);

  // 4. Setup readiness (warning-level, per unconfigured item).
  results.push(
    ...(await checkSetupReadiness({
      apiHealthy: api.state === "ok",
      apiPort: ctx.apiPort,
      webPort: ctx.webPort,
    })),
  );

  // 5. Web reachable.
  results.push(await checkWebReachable(ctx.webPort));

  // 6. Disk headroom on the Docker data root.
  results.push(await checkDiskHeadroom());

  return { results };
}
