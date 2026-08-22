/**
 * Process-level lifecycle wiring shared by every bot entry point.
 *
 * All four `index.ts` files are the same program: construct the adapter, boot
 * it, tear it down on a signal. This owns that program once — and, more
 * importantly, owns the two failure paths Node otherwise "handles" by printing
 * a raw multi-line V8 stack to stderr and exiting.
 *
 * A raw stack is the worst possible last word from a dying process: it carries
 * no `trace_id`, no `service`, no `outcome`, so the crash is invisible to every
 * dashboard — and, being neither JSON nor a single line, it breaks NDJSON
 * framing for the shipper, which can lose the lines around it too. An unhandled
 * rejection and an uncaught exception are units of work like any other, so each
 * emits one canonical `bot_event` before the process exits.
 *
 * @module
 */

import type { BotCommand } from "../types";
import { withWideEvent } from "../utils/wide-events";
import type { BaseBotAdapter } from "./base";

/** `component` (and Promtail `logger` label) for every process-lifecycle line. */
const COMPONENT = "process";

/** Signals a bot is expected to shut down gracefully on. */
const SHUTDOWN_SIGNALS = ["SIGINT", "SIGTERM"] as const;

const EXIT_OK = 0;
const EXIT_FATAL = 1;

/**
 * How long to wait for stdout to drain before forcing the exit. `console.log`
 * to a pipe — how Docker captures a container's stdout — is asynchronous, and
 * `process.exit()` discards whatever is still buffered. Without a flush the
 * line most worth keeping (the event explaining the exit) is the one most
 * likely to be lost.
 */
const STDOUT_FLUSH_TIMEOUT_MS = 2_000;

/**
 * Sets the exit code, waits for stdout to drain, then exits.
 *
 * The unref'd timer is the backstop for a blocked pipe: it cannot by itself
 * keep the event loop alive, so an already-idle process still exits with the
 * code set, and a busy one is forced out rather than hanging on a reader that
 * never drains.
 */
function exitAfterFlush(code: number): void {
  process.exitCode = code;
  const forced = setTimeout(() => process.exit(code), STDOUT_FLUSH_TIMEOUT_MS);
  forced.unref();
  process.stdout.write("", () => process.exit(code));
}

/**
 * Emits the final wide event for a process-killing fault.
 *
 * The error is re-thrown inside the boundary on purpose: that is what marks the
 * event `outcome: "failed"` and puts the real error in `errors[]`. A fault
 * event that reported success would be worse than no event at all.
 */
async function reportFault(
  platform: BaseBotAdapter["platform"],
  fault: string,
  error: unknown,
): Promise<void> {
  await withWideEvent(
    "process_fault",
    { platform, component: COMPONENT, fault, exit_code: EXIT_FATAL },
    async () => {
      throw error;
    },
  );
}

/**
 * Boots `adapter` and wires the process lifecycle around it: SIGINT/SIGTERM to
 * a graceful shutdown, and unhandled rejections / uncaught exceptions to one
 * final structured event. Call it from a bot's `index.ts` and nothing else.
 */
export function runBotProcess(
  adapter: BaseBotAdapter,
  commands: BotCommand[],
): void {
  const platform = adapter.platform;
  let exiting = false;

  /**
   * Single exit path. A second SIGTERM, or a fault raised while tearing down,
   * must not re-enter teardown — the first one already owns the exit.
   */
  const exitOnce = (code: number, finalWork: () => Promise<void>): void => {
    if (exiting) return;
    exiting = true;
    finalWork().then(
      () => exitAfterFlush(code),
      // finalWork is always wrapped in a wide-event boundary, which has already
      // recorded the failure in errors[] and emitted it. There is no caller
      // left to propagate to — only an exit code to get right.
      () => exitAfterFlush(EXIT_FATAL),
    );
  };

  for (const signal of SHUTDOWN_SIGNALS) {
    process.on(signal, () => {
      exitOnce(EXIT_OK, () => adapter.shutdown(signal));
    });
  }

  process.on("unhandledRejection", (reason) => {
    exitOnce(EXIT_FATAL, () =>
      reportFault(platform, "unhandled_rejection", reason),
    );
  });

  process.on("uncaughtException", (error) => {
    exitOnce(EXIT_FATAL, () =>
      reportFault(platform, "uncaught_exception", error),
    );
  });

  // boot() runs inside its own `bot_boot` boundary, so a boot failure is
  // already emitted with outcome=failed and the error in errors[]. All that is
  // left here is to die with the right exit code.
  void adapter.boot(commands).catch(() => {
    exitOnce(EXIT_FATAL, async () => undefined);
  });
}
