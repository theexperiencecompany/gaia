/**
 * Run `docker compose` with machine-readable progress: the raw output goes to
 * a log file, the screen gets a phase line with a size or step count, and a
 * failure becomes a {@link ComposeError} that names the cause and the log.
 * @module lib/compose-run
 */

import * as fs from "node:fs";
import { execa } from "execa";
import semver from "semver";
import { ComposeError, explainComposeFailure } from "./compose-failure.js";
import {
  applyComposeEvent,
  type ComposeEvent,
  type ComposePhase,
  createComposeProgress,
  describeComposeProgress,
} from "./compose-progress.js";
import { createLineSplitter, newLogPath } from "./logs.js";

/** First Compose whose JSON progress carries byte counts (current/total). */
export const MIN_COMPOSE_VERSION = "2.29.1";

/** Plain (non-JSON) output lines kept for explaining a failure. */
const KEPT_PLAIN_LINES = 40;

let composeVersionChecked: Promise<void> | undefined;

/** @throws Error naming both versions when Compose is too old for JSON progress. */
export function assertComposeVersion(): Promise<void> {
  composeVersionChecked ??= (async () => {
    const { stdout } = await execa("docker", ["compose", "version", "--short"]);
    const version = semver.coerce(stdout.trim());
    if (!version || semver.lt(version, MIN_COMPOSE_VERSION)) {
      throw new Error(
        `GAIA needs Docker Compose ${MIN_COMPOSE_VERSION} or newer; this machine has ${stdout.trim() || "an unknown version"}.\n` +
          "Update Docker (https://docs.docker.com/engine/install/), then try again.",
      );
    }
  })();
  return composeVersionChecked;
}

export interface ComposeRunOptions {
  cwd: string;
  /** Extra environment; it outranks infra/docker/.env in compose interpolation. */
  env?: Record<string, string>;
  timeoutMs?: number;
  /** Log file name stem, e.g. "compose-up". */
  logName: string;
  /** The command that retries with a local build, named in image errors. */
  rebuildCommand: string;
  /** Called on every progress change with the phase and the finished steps. */
  onProgress?: (phase: ComposePhase, finished: readonly string[]) => void;
}

function parseEvent(line: string): ComposeEvent | null {
  if (!line.startsWith("{")) return null;
  try {
    return JSON.parse(line) as ComposeEvent;
  } catch {
    // A plain line that happens to start with "{" is kept as plain output.
    return null;
  }
}

/**
 * Run `docker compose --progress json <args>`.
 * @throws ComposeError with the plain cause, the next step and the log path.
 */
export async function runCompose(
  args: readonly string[],
  options: ComposeRunOptions,
): Promise<void> {
  await assertComposeVersion();
  const logPath = newLogPath(options.logName);
  const log = fs.createWriteStream(logPath);
  const state = createComposeProgress();
  const plainLines: string[] = [];

  const split = createLineSplitter((line) => {
    const event = parseEvent(line);
    if (!event) {
      plainLines.push(line);
      if (plainLines.length > KEPT_PLAIN_LINES) plainLines.shift();
      return;
    }
    applyComposeEvent(state, event);
    const phase = describeComposeProgress(state);
    if (phase) options.onProgress?.(phase, state.finished);
  });

  const child = execa("docker", ["compose", "--progress", "json", ...args], {
    cwd: options.cwd,
    env: options.env,
    all: true,
    reject: false,
    timeout: options.timeoutMs,
  });
  child.all?.on("data", (data: Buffer) => {
    log.write(data);
    split(data.toString());
  });
  const result = await child;
  split("\n");
  await new Promise<void>((resolve) => log.end(resolve));

  if (result.timedOut) {
    throw new ComposeError(
      {
        cause: `Docker Compose was still running after ${Math.round((options.timeoutMs ?? 0) / 60_000)} minutes, so it was stopped.`,
        next: "Run it again; set GAIA_START_TIMEOUT_MIN to allow longer (0 = no limit).",
      },
      logPath,
    );
  }
  if (result.failed) {
    throw new ComposeError(
      explainComposeFailure(state.errors, plainLines, {
        rebuildCommand: options.rebuildCommand,
      }),
      logPath,
    );
  }
}
