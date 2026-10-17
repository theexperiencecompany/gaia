import { MARK } from "../ui/constants.js";
import type { CLIStore } from "../ui/store.js";
import {
  formatElapsed,
  type RunStep,
  type RunStepState,
  STEPS_KEY,
} from "./run-steps.js";

/** One plain line for a step that just started, finished, failed or was cancelled. */
function plainStepLine(step: RunStep): string | null {
  const took =
    step.startedAt !== undefined && step.endedAt !== undefined
      ? ` (${formatElapsed(step.endedAt - step.startedAt)})`
      : "";
  if (step.state === "active") return `  ${step.label}…`;
  if (step.state === "done") return `${MARK.ok} ${step.doneLabel}${took}`;
  if (step.state === "failed") return `${MARK.fail} ${step.label}${took}`;
  if (step.state === "cancelled")
    return `${MARK.cancelled} ${step.label}${took}`;
  return null;
}

/**
 * True only when both stdin and stdout are connected to a real TTY.
 * Ink's raw-mode rendering requires this; without it the React components
 * that call useInput throw "Raw mode is not supported".
 */
export function isInteractive(): boolean {
  return process.stdin.isTTY === true && process.stdout.isTTY === true;
}

/**
 * Exit early with a clear error when a command that cannot proceed without
 * user input is invoked outside a TTY (CI, pipes, redirected stdin, etc.).
 */
export function requireInteractive(commandName: string): void {
  if (isInteractive()) return;
  const what = commandName ? `'gaia ${commandName}'` : "this command";
  console.error(
    `Error: ${what} needs an interactive terminal (TTY) to prompt for input.`,
  );
  console.error(
    `Re-run it from a regular shell session — not a pipe, redirect, or non-TTY environment.`,
  );
  process.exit(1);
}

/**
 * Subscribe to a CLIStore and stream its state changes as plain text. Used
 * when the command is running outside a TTY: Ink cannot render, but we still
 * want to surface progress (steps, status messages, errors) on stdout/stderr.
 * A resumed step's header was already printed by the process that relaunched this one.
 */
export function attachPlainReporter(store: CLIStore, resumedStep = ""): void {
  let lastStep = resumedStep;
  let lastStatus = "";
  let lastErrorMsg = "";

  const stepStates = new Map<string, RunStepState>();
  store.on("change", (state) => {
    const steps = (state.data[STEPS_KEY] ?? []) as RunStep[];
    for (const step of steps) {
      if (stepStates.get(step.id) === step.state) continue;
      stepStates.set(step.id, step.state);
      const line = plainStepLine(step);
      if (line) console.info(line);
    }
    // A run with a step list reports through it; the bare step names add nothing.
    if (steps.length === 0 && state.step && state.step !== lastStep) {
      lastStep = state.step;
      console.info(`\n[${state.step}]`);
    }
    if (state.status && state.status !== lastStatus) {
      lastStatus = state.status;
      console.info(`  ${state.status}`);
    }
    if (state.error && state.error.message !== lastErrorMsg) {
      lastErrorMsg = state.error.message;
      console.error(`  Error: ${state.error.message}`);
    }
  });
}
