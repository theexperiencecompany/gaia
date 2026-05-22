import type { CLIStore } from "../ui/store.js";

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
 */
export function attachPlainReporter(store: CLIStore): void {
  let lastStep = "";
  let lastStatus = "";
  let lastErrorMsg = "";

  store.on("change", (state) => {
    if (state.step && state.step !== lastStep) {
      lastStep = state.step;
      console.log(`\n[${state.step}]`);
    }
    if (state.status && state.status !== lastStatus) {
      lastStatus = state.status;
      console.log(`  ${state.status}`);
    }
    if (state.error && state.error.message !== lastErrorMsg) {
      lastErrorMsg = state.error.message;
      console.error(`  Error: ${state.error.message}`);
    }
  });
}
