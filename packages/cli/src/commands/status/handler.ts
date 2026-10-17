/**
 * Handler for the 'status' command — shows service health.
 * @module commands/status/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import type { DependencyReadiness } from "../../lib/dependency-readiness.js";
import { dependencyName, serviceName } from "../../lib/display-names.js";
import type { DockerStatus, ServiceStatus } from "../../lib/healthcheck.js";
import { MARK } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";
import { runStatusFlow } from "./flow.js";

export async function runStatus(): Promise<void> {
  await runCommandUI({
    command: "status",
    whenNonInteractive: "plain",
    // The interactive screen loops on an "exit_or_refresh" prompt; in plain
    // mode resolve it to "exit" so the snapshot prints once and the process
    // terminates instead of hanging.
    autoResolve: [["exit_or_refresh", "exit"]],
    runFlow: runStatusFlow,
    onPlainComplete: printStatusSnapshot,
  });
}

const NAME_WIDTH = 20;

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

function row(ok: boolean, name: string, detail = ""): void {
  out(
    `  ${ok ? MARK.ok : MARK.fail} ${name.padEnd(NAME_WIDTH)} ${detail}`.trimEnd(),
  );
}

/** Renders the collected status as plain text for non-TTY environments. */
function printStatusSnapshot(store: CLIStore): void {
  const { data } = store.currentState;
  out(`\nGAIA status: ${store.currentState.status}`);
  out(`  ${data.install}`);
  printDocker(data.docker as DockerStatus | undefined);
  printServices((data.services ?? []) as ServiceStatus[]);
  printReadiness(data.readiness as DependencyReadiness | undefined);
}

function printDocker(docker: DockerStatus | undefined): void {
  if (!docker) return;
  if (docker.problem) {
    out("\nDocker");
    row(false, docker.problem.summary);
    out(`    ${docker.problem.fix}`);
    return;
  }
  if (docker.containers.length === 0) return;
  out("\nServices");
  for (const container of docker.containers) {
    row(
      container.status === "running",
      serviceName(container.name),
      container.health ?? container.status,
    );
  }
}

function printServices(services: ServiceStatus[]): void {
  if (services.length === 0) return;
  out("\nLocal services");
  for (const service of services) {
    row(
      service.status === "up",
      `${service.name} (:${service.port})`,
      service.latency === undefined ? "" : `${service.latency} ms`,
    );
  }
}

function printReadiness(readiness: DependencyReadiness | undefined): void {
  if (!readiness) return;
  out("\nBacking services");
  if (!readiness.reachable) {
    row(false, "Not checked", readiness.detail);
    return;
  }
  for (const dependency of readiness.dependencies) {
    const error = dependency.error_type ? `  ${dependency.error_type}` : "";
    row(
      dependency.ok,
      dependencyName(dependency.name),
      `${dependency.latency_ms} ms${error}`,
    );
    if (dependency.fix) out(`    ${dependency.fix}`);
  }
}
