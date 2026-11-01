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

import { readConfig } from "../../lib/config.js";
import {
  COMPOSE_PROJECT_BY_MODE,
  type ComposeProject,
} from "../../lib/docker.js";
import { getDockerAccess } from "../../lib/docker-access.js";
import {
  installWebUrl,
  localApiUrl,
  localOrigin,
} from "../../lib/endpoints.js";
import type { SetupMode } from "../../lib/env-parser.js";
import {
  readDockerComposePortOverrides,
  readGaiaDomain,
} from "../../lib/env-writer.js";
import {
  describeInstall,
  detectSetupMode,
  findInstallRoot,
} from "../../lib/install-root.js";
import {
  checkApiHealth,
  checkBots,
  checkComposeContainers,
  checkDependencies,
  checkDiskHeadroom,
  checkDockerDaemon,
  checkMemoryHeadroom,
  checkPortConflicts,
  checkReleaseVersion,
  checkSetupReadiness,
  checkWebReachable,
  EXPECTED_SERVICES,
  resolvePort,
  unconfiguredInstallCheck,
} from "./checks.js";
import type { CheckResult } from "./types.js";

export interface DoctorReport {
  /** Which installation the checks ran against, e.g. "/home/me/gaia (selfhost mode)". */
  install: string;
  /** False when there is no install to describe (the GAIA row already says so). */
  installed: boolean;
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
  repoPath: string | null;
  /** Where the API answers on this machine for the detected mode. */
  origin: string;
  /** API base (`…/api/v1`) on this machine for the detected mode. */
  apiUrl: string;
  webPort: number;
  overrides: Record<number, number>;
  /** The public domain the install serves, which pins it to ports 80 and 443. */
  domain?: string;
  /** Detected setup mode, or null when the repo is not configured. */
  mode: SetupMode | null;
  /** Compose project name, or null when the setup mode is undetectable. */
  project: ComposeProject | null;
}

async function resolveContext(): Promise<DoctorContext> {
  const repoPath = findInstallRoot();
  const overrides = repoPath ? readDockerComposePortOverrides(repoPath) : {};
  const mode = repoPath ? await detectSetupMode(repoPath) : null;

  return {
    repoPath,
    // Unconfigured repos probe the self-host origin, the default install.
    origin: localOrigin(mode ?? "selfhost", overrides),
    apiUrl: localApiUrl(mode ?? "selfhost", overrides),
    webPort: resolvePort(overrides, 3000),
    overrides,
    domain: repoPath ? readGaiaDomain(repoPath) : undefined,
    mode,
    project: mode ? COMPOSE_PROJECT_BY_MODE[mode] : null,
  };
}

/** Run every check in order; onResult hears each result as it lands. */
export async function runDoctorChecks(
  onResult: (result: CheckResult) => void = () => undefined,
): Promise<DoctorReport> {
  const results: CheckResult[] = [];
  const add = (...found: CheckResult[]): void => {
    results.push(...found);
    for (const result of found) onResult(result);
  };
  const [ctx, dockerAccess] = await Promise.all([
    resolveContext(),
    getDockerAccess(),
  ]);

  // 1. Docker usable by this user.
  add(await checkDockerDaemon(dockerAccess));

  // 1b. Host port conflicts (respects the compose env file's overrides).
  add(
    dockerAccess === "ready"
      ? await checkPortConflicts(
          ctx.mode ?? "selfhost",
          ctx.overrides,
          ctx.domain,
        )
      : {
          id: "port-conflict",
          label: "Ports",
          severity: "blocker",
          state: "skipped",
          detail: "they need Docker",
        },
  );

  // Nothing installed: one row says so, and the checks of a running GAIA
  // are not run (they would only repeat "not answering" with a wrong fix).
  if (!ctx.repoPath || !ctx.project || !ctx.mode) {
    add(unconfiguredInstallCheck(ctx.repoPath));
    for (const label of ["API", "Setup", "Web app"]) {
      add({
        label,
        severity: "blocker",
        state: "skipped",
        detail: "GAIA isn't installed",
      });
    }
    add(await checkDiskHeadroom("install"));
    add(await checkMemoryHeadroom());
    return {
      install: describeInstall(ctx.repoPath, ctx.mode),
      installed: false,
      results,
    };
  }
  const startCommand = ctx.mode === "developer" ? "gaia dev" : "gaia start";

  // 2. Compose project containers.
  add(
    await checkComposeContainers({
      project: ctx.project,
      expected: EXPECTED_SERVICES[ctx.project],
    }),
  );

  // 2b. Each enabled chat bot (self-host only).
  if (ctx.project === COMPOSE_PROJECT_BY_MODE.selfhost) {
    add(...(await checkBots(readConfig()?.bots ?? [], ctx.project)));
  }

  // 3. API health.
  const api = await checkApiHealth(ctx.apiUrl, startCommand);
  add(api);

  // 3b. Every backing service the API needs, from /health/ready.
  add(
    ...(await checkDependencies({
      apiHealthy: api.state === "ok",
      origin: ctx.origin,
      project: ctx.project,
    })),
  );

  // 4. Setup readiness (warning-level, per unconfigured item).
  add(
    ...(await checkSetupReadiness({
      apiHealthy: api.state === "ok",
      apiUrl: ctx.apiUrl,
      webUrl: installWebUrl(ctx.repoPath, ctx.webPort),
    })),
  );

  // 5. Web reachable.
  add(await checkWebReachable(ctx.webPort, startCommand));

  // 6. Disk headroom on the Docker data root.
  add(await checkDiskHeadroom("run"));

  // 7. Memory headroom.
  add(await checkMemoryHeadroom());

  // 8. Release drift — warns when the images are not this CLI's release.
  add(await checkReleaseVersion(ctx.repoPath, ctx.mode));

  return {
    install: describeInstall(ctx.repoPath, ctx.mode),
    installed: true,
    results,
  };
}
