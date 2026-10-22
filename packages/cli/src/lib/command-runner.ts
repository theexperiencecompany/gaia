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
import { HANDED_OVER_KEY, MARK } from "../ui/constants.js";
import { printHeader } from "../ui/header/header-lines.js";
import { type CLIStore, createStore } from "../ui/store.js";
import type { PresetAnswers } from "../ui/store.types.js";
import { endingLines, readEnding } from "./command-ending.js";
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
  /** Answers to give in plain mode instead of prompting (e.g. trailing "exit" prompts). */
  autoResolve?: PresetAnswers;
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
  // A docker-group relaunch continues its parent's output, header included.
  if (!resumedStep())
    await printHeader({ showStatus: false, showUpdate: false });
  attachPlainReporter(store);
  if (runtime.autoResolve) store.setAutoResolve(runtime.autoResolve);
  try {
    await runtime.runFlow(store);
    // The last step change may still sit in the store's throttle: print it before the ending.
    store.flush();
    const groupSwitch = dockerGroupRelaunch(store);
    if (groupSwitch) {
      await relaunchWithDockerGroup(groupSwitch, {
        step: store.currentState.step,
        steps: resumableSteps(store),
      });
    }
    runtime.onPlainComplete?.(store);
    const ending = readEnding(store);
    if (ending && !store.currentState.error) {
      for (const line of endingLines(ending)) console.info(line);
    }
  } catch (error) {
    // A flow that throws leaves no row spinning: its running step turns red.
    endActiveStep(store, "failed");
    store.setError(error as Error);
  }
  exitForStore(store);
}

/** CSI F: the cursor to the start of the line above. */
const CURSOR_TO_PREVIOUS_LINE = "\u001b[1F";

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
  const { unmount } = render(
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
    process.stdout.write(`\n  ${MARK.cancelled} Cancelled.${hint}\n`);
    process.exit(SIGINT_EXIT_CODE);
  };
  cancel = handleExit;
  process.once("SIGINT", handleExit);
  process.once("SIGTERM", handleExit);

  try {
    await runtime.runFlow(store);
  } catch (error) {
    // A flow that throws leaves no row spinning: its running step turns red.
    endActiveStep(store, "failed");
    store.setError(error as Error);
  } finally {
    process.off("SIGINT", handleExit);
    process.off("SIGTERM", handleExit);
  }

  // The flow's last state (stop's result line, up's summary) must be on screen before it unmounts.
  await drawLastChange(store);
  const groupSwitch = dockerGroupRelaunch(store);
  if (groupSwitch) {
    // The relaunched process draws the live lines again: take this one's down
    // first, so the run reads as one screen. Ink's clear() races its throttled
    // writes (a spinner keeps one pending), erasing written lines instead.
    store.updateData(HANDED_OVER_KEY, true);
    await drawLastChange(store);
    unmount();
    // Ink ends even an empty frame with a newline: the relaunch starts on that line, not under it.
    process.stdout.write(CURSOR_TO_PREVIOUS_LINE);
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
