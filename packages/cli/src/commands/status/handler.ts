import { render } from "ink";
import React from "react";
import { attachPlainReporter, isInteractive } from "../../lib/non-tty.js";
import { App } from "../../ui/app.js";
import { createStore } from "../../ui/store.js";
import { runStatusFlow } from "./flow.js";

export async function runStatus(): Promise<void> {
  const store = createStore();

  if (!isInteractive()) {
    // Non-TTY: render results as plain text and exit instead of looping on
    // an interactive refresh prompt.
    attachPlainReporter(store);
    store.setAutoResolve("exit_or_refresh", "exit");
    try {
      await runStatusFlow(store);
      printStatusSnapshot(store);
    } catch (error) {
      store.setError(error as Error);
    }
    process.exit(store.currentState.error ? 1 : 0);
  }

  const { unmount } = render(
    React.createElement(App, { store, command: "status" }),
  );

  // Wait a tick for ink to fully initialize and measure terminal dimensions
  // before running the flow, otherwise ink-big-text may fall back to plain text
  await new Promise((resolve) => setTimeout(resolve, 50));

  try {
    await runStatusFlow(store);
  } catch (error) {
    store.setError(error as Error);
  }

  if (store.currentState.error) {
    await store.waitForInput("exit");
  }

  unmount();
  process.exit(store.currentState.error ? 1 : 0);
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

function printStatusSnapshot(store: ReturnType<typeof createStore>): void {
  const services = (store.currentState.data.services ?? []) as PlainService[];
  const docker = store.currentState.data.docker as
    | { running: boolean; containers: PlainContainer[] }
    | undefined;

  if (services.length > 0) {
    // biome-ignore lint/suspicious/noConsole: this IS the UI layer in non-TTY mode
    console.log("\nServices:");
    for (const s of services) {
      const tag = s.status === "up" ? "UP" : "DOWN";
      const latency = s.latency ? `${s.latency}ms` : "--";
      // biome-ignore lint/suspicious/noConsole: this IS the UI layer in non-TTY mode
      console.log(`  ${s.name.padEnd(12)} :${s.port}  ${tag}  ${latency}`);
    }
  }

  if (docker) {
    // biome-ignore lint/suspicious/noConsole: this IS the UI layer in non-TTY mode
    console.log(`\nDocker: ${docker.running ? "running" : "not running"}`);
    for (const c of docker.containers ?? []) {
      const health = c.health ? ` (${c.health})` : "";
      // biome-ignore lint/suspicious/noConsole: this IS the UI layer in non-TTY mode
      console.log(`  ${c.name.padEnd(14)} ${c.status}${health}`);
    }
  }
}
