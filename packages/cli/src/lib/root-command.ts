/**
 * Commands that need root (apt, Docker's installer, usermod), run so their
 * output lands in a log file and never on the screen Ink is drawing.
 * @module lib/root-command
 */

import * as fs from "node:fs";
import { execa } from "execa";
import { createLineSplitter } from "./logs.js";

function isRoot(): boolean {
  return typeof process.getuid === "function" && process.getuid() === 0;
}

/**
 * Make sure sudo will not prompt mid-command. When it needs a password, ask
 * once here: sudo reads it from the terminal itself.
 */
async function ensureSudoSession(): Promise<void> {
  if (isRoot()) return;
  const cached = await execa("sudo", ["-n", "true"], { reject: false });
  if (!cached.failed) return;
  await execa("sudo", ["-v", "-p", "[sudo] password for %u: "], {
    stdio: "inherit",
  });
}

/**
 * Run `command args` as root with stdout and stderr appended to logPath.
 * onLine receives each output line as it arrives, for a progress label.
 * @throws Error naming the log file when the command fails.
 */
export async function runAsRoot(
  command: string,
  args: readonly string[],
  logPath: string,
  onLine?: (line: string) => void,
): Promise<void> {
  await ensureSudoSession();
  const [file, fileArgs] = isRoot()
    ? [command, [...args]]
    : ["sudo", ["-n", command, ...args]];
  const log = fs.createWriteStream(logPath, { flags: "a" });
  const split = createLineSplitter((line) => onLine?.(line));
  const child = execa(file, fileArgs, { all: true, reject: false });
  child.all?.on("data", (data: Buffer) => {
    log.write(data);
    split(data.toString());
  });
  const result = await child;
  await new Promise<void>((resolve) => log.end(resolve));
  if (result.failed) {
    throw new Error(
      `'${[command, ...args].join(" ")}' failed (exit ${result.exitCode ?? "unknown"}). Its output is in ${logPath}`,
    );
  }
}
