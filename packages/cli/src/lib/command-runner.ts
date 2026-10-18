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
import { MARK } from "../ui/constants.js";
import { type CLIStore, createStore } from "../ui/store.js";
import {
  type DockerGroupSwitch,
  relaunchWithDockerGroup,
  resumedStep,
} from "./docker-group.js";
import { SIGINT_EXIT_CODE } from "./exit-codes.js";
import {
  attachPlainReporter,
  isInteractive,
  requireInteractive,
} from "./non-tty.js";
import { endActiveStep, resumableSteps } from "./run-steps.js";

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
  /** Said after "Cancelled." on Ctrl-C: what state things are in and how to resume. */
  cancelHint?: string;
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
  attachPlainReporter(store, resumedStep());
  for (const [id, value] of runtime.autoResolve ?? []) {
    store.setAutoResolve(id, value);
  }
  try {
    await runtime.runFlow(store);
    const groupSwitch = dockerGroupRelaunch(store);
    if (groupSwitch) {
      await relaunchWithDockerGroup(groupSwitch, {
        step: store.currentState.step,
        steps: resumableSteps(store),
      });
    }
    runtime.onPlainComplete?.(store);
  } catch (error) {
    store.setError(error as Error);
  }
  exitForStore(store);
}

/** Ink draws at most this often; a committed change is on screen within a frame. */
const RENDER_FPS = 30;
const FRAME_MS = Math.ceil(1000 / RENDER_FPS);

/**
 * Put the store's last change on screen before unmounting: once a screen has
 * written Static output, Ink's unmount skips its final frame and keeps the
 * last one it drew. Two frames cover the throttled render and the throttled write.
 */
async function drawLastChange(store: CLIStore): Promise<void> {
  store.flush();
  await new Promise((resolve) => setTimeout(resolve, 2 * FRAME_MS));
}

async function runInk(store: CLIStore, runtime: CommandRuntime): Promise<void> {
  // Ctrl-C reaches the flow as a cancel (below), not as Ink quietly unmounting
  // while the work carries on and the process exits 0.
  let cancel = async (): Promise<void> => undefined;
  const { unmount, clear } = render(
    React.createElement(App, {
      store,
      command: runtime.command,
      onCancel: () => void cancel(),
    }),
    { exitOnCtrlC: false, maxFps: RENDER_FPS },
  );

  const handleExit = async (): Promise<void> => {
    // The last frame stays on screen: end its running step, not a frozen spinner.
    endActiveStep(store, "cancelled");
    await drawLastChange(store);
    unmount();
    const hint = runtime.cancelHint ? ` ${runtime.cancelHint}` : "";
    process.stdout.write(`\n${MARK.cancelled} Cancelled.${hint}\n`);
    process.exit(SIGINT_EXIT_CODE);
  };
  cancel = handleExit;
  process.once("SIGINT", handleExit);
  process.once("SIGTERM", handleExit);

  try {
    await runtime.runFlow(store);
  } catch (error) {
    store.setError(error as Error);
  } finally {
    process.off("SIGINT", handleExit);
    process.off("SIGTERM", handleExit);
  }

  // The flow's last state (stop's result line, up's summary) must be on screen before it unmounts.
  await drawLastChange(store);
  const groupSwitch = dockerGroupRelaunch(store);
  if (groupSwitch) {
    // The relaunched process draws the same screen again: erase this one so
    // the run reads as one screen, not two stacked copies.
    clear();
    unmount();
    await relaunchWithDockerGroup(groupSwitch, {
      step: store.currentState.step,
      steps: resumableSteps(store),
    });
  }
  unmount();
  // Ink leaves the cursor at the end of its last line; the shell prompt
  // belongs on its own line.
  process.stdout.write("\n");
  exitForStore(store);
}

/** How to relaunch, when the flow granted the docker group and stopped (ensureDocker). */
function dockerGroupRelaunch(store: CLIStore): DockerGroupSwitch | undefined {
  if (store.currentState.error) return undefined;
  return store.currentState.data.dockerGroupSwitch;
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
  // A flow may set a failing exit code without an error (status with a part down).
  const code = store.currentState.error ? 1 : Number(process.exitCode ?? 0);
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
