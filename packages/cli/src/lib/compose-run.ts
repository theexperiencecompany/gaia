/**
 * Run `docker compose` with machine-readable progress: the raw output goes to
 * a log file, the screen gets a phase line with a size or step count, and a
 * failure becomes a {@link ComposeError} that names the cause and the log.
 * @module lib/compose-run
 */

import * as fs from "node:fs";
import { execa } from "execa";
import { ComposeError, explainComposeFailure } from "./compose-failure.js";
import {
  applyComposeEvent,
  createComposeProgress,
  describeComposeProgress,
} from "./compose-progress.js";
import type { ComposeEvent, ComposePhase } from "./compose-progress.types.js";
import { assertDockerSupportsGaia } from "./docker.js";
import { createLineSplitter, newLogPath } from "./logs.js";
import type { PullSize } from "./pull-size.js";

/** Plain (non-JSON) output lines kept for explaining a failure. */
const KEPT_PLAIN_LINES = 40;

let dockerVersionsChecked: Promise<void> | undefined;

/** What a successful run did. */
export interface ComposeRunResult {
  /** Services this run started; 0 when all were already running. */
  startedServices: number;
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
  /** What the pull will download, measured beforehand (see measurePull). */
  pullSize?: PullSize;
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
): Promise<ComposeRunResult> {
  dockerVersionsChecked ??= assertDockerSupportsGaia();
  await dockerVersionsChecked;
  const logPath = newLogPath(options.logName);
  const log = fs.createWriteStream(logPath);
  const pullSize = options.pullSize;
  if (pullSize && "unknown" in pullSize) {
    log.write(
      `gaia: the download's size is an estimate: ${pullSize.unknown}\n`,
    );
  }
  const state = createComposeProgress(
    pullSize && "layers" in pullSize ? pullSize.layers : undefined,
  );
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
  return { startedServices: state.started.size };
}
