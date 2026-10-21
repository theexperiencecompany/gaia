/**
 * Log files for the long, noisy commands the CLI runs (Docker's installer,
 * compose pulls and builds). Their output goes here instead of the terminal,
 * and a failure names the file.
 * @module lib/logs
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { GAIA_CONFIG_DIR } from "./config.js";

export const GAIA_LOG_DIR = path.join(GAIA_CONFIG_DIR, "logs");

/** A fresh, empty log file path such as ~/.gaia/logs/docker-install-2026-10-17T21-08-34.log. */
export function newLogPath(name: string, now: Date = new Date()): string {
  fs.mkdirSync(GAIA_LOG_DIR, { recursive: true });
  const stamp = now.toISOString().slice(0, 19).replaceAll(":", "-");
  return path.join(GAIA_LOG_DIR, `${name}-${stamp}.log`);
}

/** " (log: <path>)" for an error line, or nothing when no output ever reached the log. */
export function existingLogNote(logPath: string): string {
  const written = fs.existsSync(logPath) && fs.statSync(logPath).size > 0;
  return written ? ` (log: ${logPath})` : "";
}

/** Split streamed chunks into whole lines; a partial last line waits for the next chunk. */
export function createLineSplitter(
  onLine: (line: string) => void,
): (chunk: string) => void {
  let pending = "";
  return (chunk) => {
    const parts = (pending + chunk).split(/\r?\n|\r/);
    pending = parts.pop() ?? "";
    for (const part of parts) {
      if (part.trim()) onLine(part);
    }
  };
}
