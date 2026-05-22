/**
 * Shared lifecycle for the Ink-based commands (init/setup/status/start/stop).
 *
 * Every one of those handlers used to repeat the same dance: create the store,
 * branch on TTY availability, render Ink (or stream plain text), install
 * SIGINT/SIGTERM handlers, run the flow, wait on the trailing error prompt,
 * and exit with the right code. This module centralises that so each handler
 * only has to declare *what* flow to run and *how* it behaves without a TTY.
 *
 * @module lib/command-runner
 */

import { render } from "ink";
import React from "react";
import { App, type CLICommand } from "../ui/app.js";
import { type CLIStore, createStore } from "../ui/store.js";
import {
  attachPlainReporter,
  isInteractive,
  requireInteractive,
} from "./non-tty.js";

/**
 * Give Ink a tick to initialize and measure the terminal before the flow runs.
 * Without it, ink-big-text occasionally falls back to plain rendering because
 * dimensions aren't available yet.
 */
const INK_INIT_DELAY_MS = 50;

/** Exit code POSIX shells report for a process terminated by SIGINT. */
const SIGINT_EXIT_CODE = 130;

/** An input id to resolve automatically in plain mode, with an optional value. */
type AutoResolve = readonly [id: string, value?: unknown];

interface CommandRuntime {
  /** Selects the Ink screen to render and labels non-TTY error output. */
  command: CLICommand;
  /** Imperative flow that drives the store. */
  runFlow: (store: CLIStore) => Promise<void>;
  /**
   * Behaviour when stdin/stdout is not a TTY:
   * - "fail": the flow needs interactive input, so exit early with an error.
   * - "plain": stream state changes as text instead of rendering Ink.
   */
  whenNonInteractive: "fail" | "plain";
  /** Input ids to auto-resolve in plain mode (e.g. trailing "exit" prompts). */
  autoResolve?: readonly AutoResolve[];
  /** Plain-mode hook to print a final snapshot once the flow succeeds. */
  onPlainComplete?: (store: CLIStore) => void;
}

/**
 * Runs a command's flow under either an Ink UI or a plain non-TTY reporter,
 * then exits the process with status 1 if the store ended in an error state.
 */
export async function runCommandUI(runtime: CommandRuntime): Promise<void> {
  const store = createStore();

  if (runtime.whenNonInteractive === "fail") {
    requireInteractive(runtime.command); // exits the process when not a TTY
    await runInk(store, runtime);
    return;
  }

  if (isInteractive()) {
    await runInk(store, runtime);
  } else {
    await runPlain(store, runtime);
  }
}

async function runPlain(
  store: CLIStore,
  runtime: CommandRuntime,
): Promise<void> {
  attachPlainReporter(store);
  for (const [id, value] of runtime.autoResolve ?? []) {
    store.setAutoResolve(id, value);
  }
  try {
    await runtime.runFlow(store);
    runtime.onPlainComplete?.(store);
  } catch (error) {
    store.setError(error as Error);
  }
  exitForStore(store);
}

async function runInk(store: CLIStore, runtime: CommandRuntime): Promise<void> {
  const { unmount } = render(
    React.createElement(App, { store, command: runtime.command }),
  );

  const handleExit = () => {
    unmount();
    process.exit(SIGINT_EXIT_CODE);
  };
  process.once("SIGINT", handleExit);
  process.once("SIGTERM", handleExit);

  await new Promise((resolve) => setTimeout(resolve, INK_INIT_DELAY_MS));

  try {
    await runtime.runFlow(store);
  } catch (error) {
    store.setError(error as Error);
  } finally {
    process.off("SIGINT", handleExit);
    process.off("SIGTERM", handleExit);
  }

  if (store.currentState.error) {
    await store.waitForInput("exit");
  }

  unmount();
  exitForStore(store);
}

/**
 * Exit with status 1 when the store ended in an error, else 0 — but let any
 * buffered stdout/stderr drain first. process.exit() can terminate mid-write
 * and truncate piped (non-TTY) output, so we only force-exit once the streams
 * are flushed. (Setting process.exitCode and returning instead would let the
 * undici keep-alive sockets from the health checks delay exit by several
 * seconds, so we force-exit after the drain.)
 */
function exitForStore(store: CLIStore): void {
  const code = store.currentState.error ? 1 : 0;
  const pending = [process.stdout, process.stderr].filter(
    (stream) => stream.writableLength > 0,
  );

  if (pending.length === 0) {
    process.exit(code);
  }

  let remaining = pending.length;
  for (const stream of pending) {
    stream.once("drain", () => {
      remaining -= 1;
      if (remaining === 0) process.exit(code);
    });
  }
}
