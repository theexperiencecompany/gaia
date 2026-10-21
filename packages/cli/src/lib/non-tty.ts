import { MARK } from "../ui/constants.js";
import type { CLIStore } from "../ui/store.js";
import { printError, printStepError } from "./print-error.js";
import { formatElapsed, type RunStep, STEPS_KEY } from "./run-steps.js";
import { stepRowText } from "./step-row.js";

/** A step's row two columns in, its time right-aligned as on the screen; endedAt stands in for a step still running. */
function plainRow(
  mark: string,
  label: string,
  step: RunStep,
  endedAt = step.endedAt,
): string {
  const time =
    step.startedAt !== undefined && endedAt !== undefined
      ? formatElapsed(endedAt - step.startedAt)
      : "";
  return `  ${stepRowText(mark, label, time)}`.trimEnd();
}

/** One plain line for a step that just finished, failed or was cancelled; a running one has its status lines. */
function plainStepLine(step: RunStep): string | null {
  if (step.state === "done") {
    return [
      plainRow(MARK.ok, step.doneLabel, step),
      ...(step.warnings ?? []).map((warning) => `    ${MARK.warn} ${warning}`),
    ].join("\n");
  }
  if (step.state === "failed") {
    return plainRow(MARK.fail, step.failedLabel ?? step.label, step);
  }
  if (step.state === "cancelled") {
    return plainRow(MARK.cancelled, step.label, step);
  }
  return null;
}

/**
 * A run's error under the step it stopped. A flow records its error before it
 * ends the running step, so that step's ✗ row is printed first, and marked
 * seen so the step's own failed state doesn't print it again.
 */
function printRunError(
  message: string,
  steps: readonly RunStep[],
  stepStates: Map<string, string>,
): void {
  const running = steps.find((step) => step.state === "active");
  if (running) {
    stepStates.set(running.id, "failed:");
    console.info(
      plainRow(
        MARK.fail,
        running.failedLabel ?? running.label,
        running,
        Date.now(),
      ),
    );
  }
  if (running || steps.some((step) => step.state === "failed")) {
    printStepError(message);
  } else {
    printError(message);
  }
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
  printError(
    `${what} needs an interactive terminal to ask its questions.\n` +
      "Run it from a regular terminal, not a pipe or a script.",
  );
  process.exit(1);
}

/**
 * Subscribe to a CLIStore and stream its state changes as plain text. Used
 * when the command is running outside a TTY: Ink cannot render, but we still
 * want to surface progress (steps, status messages, errors) on stdout/stderr.
 */
export function attachPlainReporter(store: CLIStore): void {
  let lastStatus = "";
  let lastErrorMsg = "";

  // A running step that changes its heading (downloading, then installing) says so once more.
  const stepStates = new Map<string, string>();
  store.on("change", (state) => {
    const steps = (state.data[STEPS_KEY] ?? []) as RunStep[];
    for (const step of steps) {
      const seen = `${step.state}:${step.state === "active" ? step.label : ""}`;
      if (stepStates.get(step.id) === seen) continue;
      stepStates.set(step.id, seen);
      const line = plainStepLine(step);
      if (line) console.info(line);
    }
    if (state.status && state.status !== lastStatus) {
      lastStatus = state.status;
      console.info(`    ${state.status}`);
    }
    if (state.error && state.error.message !== lastErrorMsg) {
      lastErrorMsg = state.error.message;
      printRunError(state.error.message, steps, stepStates);
    }
  });
}
