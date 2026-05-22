/**
 * Handler for the 'status' command — shows service health.
 * @module commands/status/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
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

interface PlainService {
  name: string;
  port: number;
  status: "up" | "down" | "unknown";
  latency?: number;
}

interface PlainContainer {
  name: string;
  status: "running" | "stopped" | "not_found";
  health?: string;
}

interface PlainDocker {
  running: boolean;
  containers: PlainContainer[];
}

/** Renders the collected status as plain text for non-TTY environments. */
function printStatusSnapshot(store: CLIStore): void {
  const services = (store.currentState.data.services ?? []) as PlainService[];
  const docker = store.currentState.data.docker as PlainDocker | undefined;
  printServices(services);
  printDocker(docker);
}

function statusTag(status: PlainService["status"]): string {
  if (status === "up") return "UP";
  if (status === "down") return "DOWN";
  return "UNKNOWN";
}

function printServices(services: PlainService[]): void {
  if (services.length === 0) return;
  console.log("\nServices:");
  for (const service of services) {
    const tag = statusTag(service.status);
    const latency =
      service.latency === undefined ? "--" : `${service.latency}ms`;
    const name = service.name.padEnd(12);
    console.log(`  ${name} :${service.port}  ${tag}  ${latency}`);
  }
}

function printDocker(docker: PlainDocker | undefined): void {
  if (!docker) return;
  console.log(`\nDocker: ${docker.running ? "running" : "not running"}`);
  for (const container of docker.containers ?? []) {
    const health = container.health ? ` (${container.health})` : "";
    const name = container.name.padEnd(14);
    console.log(`  ${name} ${container.status}${health}`);
  }
}
