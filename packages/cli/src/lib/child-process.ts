/**
 * Running child processes: captured (runCommand) or on this terminal
 * (runInteractiveCommand). Compose runs with progress go through compose-run.ts.
 * @module lib/child-process
 */

import { spawn } from "child_process";
import { execa } from "execa";

/** Whole lines of a failed command's output an error quotes; never a cut mid-word. */
const ERROR_TAIL_LINES = 8;

/** Progress runCommand reports per output chunk, and its ceiling until the command exits. */
const PROGRESS_PER_CHUNK = 5;
const PROGRESS_CEILING = 95;

export interface RunCommandOptions {
  cwd: string;
  /** Extra environment, merged over this process's. */
  env?: Record<string, string>;
  /** Each chunk of stdout and stderr, as it arrives. */
  onLog?: (chunk: string) => void;
  /** A rough 0-100: it rises with output and reaches 100 on success. */
  onProgress?: (progress: number) => void;
}

function lastLines(output: string, count: number): string {
  return output.trimEnd().split("\n").slice(-count).join("\n");
}

/**
 * Run a command with its output captured, never through a shell.
 * @throws Error "Command failed with code N:" plus the output's last lines.
 */
export async function runCommand(
  cmd: string,
  args: readonly string[],
  options: RunCommandOptions,
): Promise<void> {
  const child = execa(cmd, args, {
    cwd: options.cwd,
    env: options.env,
    stdin: "ignore",
    all: true,
    reject: false,
  });
  let progress = 0;
  child.all?.on("data", (data: Buffer) => {
    options.onLog?.(data.toString());
    progress = Math.min(progress + PROGRESS_PER_CHUNK, PROGRESS_CEILING);
    options.onProgress?.(progress);
  });
  const result = await child;
  if (result.failed) {
    // No exit code: it never started (ENOENT, EACCES), and execa's error says so.
    if (result.exitCode === undefined) throw result;
    throw new Error(
      `Command failed with code ${result.exitCode}:\n${lastLines(result.all ?? "", ERROR_TAIL_LINES)}`,
    );
  }
  options.onProgress?.(100);
}

export interface InteractiveCommand {
  cmd: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
  onSpawn?: (pid: number | undefined) => void;
  detached?: boolean;
}

export async function runInteractiveCommand(
  cmd: string,
  args: string[],
  cwd: string,
  env?: Record<string, string>,
  onSpawn?: (pid: number | undefined) => void,
  detached = false,
): Promise<void> {
  await runConcurrentInteractiveCommands([
    { cmd, args, cwd, env, onSpawn, detached },
  ]);
}

export async function runConcurrentInteractiveCommands(
  commands: InteractiveCommand[],
): Promise<void> {
  if (commands.length === 0) {
    return;
  }

  await new Promise<void>((resolve, reject) => {
    const processes = commands.map((command) =>
      spawn(command.cmd, command.args, {
        cwd: command.cwd,
        stdio: "inherit",
        shell: false,
        detached: command.detached ?? false,
        env: command.env ? { ...process.env, ...command.env } : process.env,
      }),
    );
    processes.forEach((proc, index) => {
      commands[index]?.onSpawn?.(proc.pid);
    });

    let settled = false;
    let closedCount = 0;
    let stopping = false;
    let shutdownTimer: ReturnType<typeof setTimeout> | undefined;

    const cleanupSignalHandlers = () => {
      process.off("SIGINT", onSignal);
      process.off("SIGTERM", onSignal);
    };

    const stopAll = () => {
      if (stopping) return;
      stopping = true;
      for (const [index, proc] of processes.entries()) {
        const command = commands[index];
        try {
          if (
            process.platform !== "win32" &&
            command?.detached &&
            typeof proc.pid === "number"
          ) {
            process.kill(-proc.pid, "SIGTERM");
          } else {
            proc.kill("SIGTERM");
          }
        } catch {
          // ignore
        }
      }
      shutdownTimer = setTimeout(() => {
        for (const [index, proc] of processes.entries()) {
          const command = commands[index];
          try {
            if (
              process.platform !== "win32" &&
              command?.detached &&
              typeof proc.pid === "number"
            ) {
              process.kill(-proc.pid, "SIGKILL");
            } else {
              proc.kill("SIGKILL");
            }
          } catch {
            // ignore
          }
        }
      }, 1000);
    };

    const onSignal = () => {
      stopAll();
    };

    process.on("SIGINT", onSignal);
    process.on("SIGTERM", onSignal);

    processes.forEach((proc, index) => {
      const command = commands[index];
      proc.on("error", (error) => {
        if (settled) return;
        settled = true;
        cleanupSignalHandlers();
        stopAll();
        reject(error);
      });

      proc.on("close", (code, signal) => {
        closedCount += 1;

        // Treat SIGINT / SIGTERM as a clean exit: foreground commands like `gaia logs` and
        // `gaia dev` are *expected* to be Ctrl-C'd, and a signal-terminated child reports code
        // 128+N (130 for SIGINT, 143 for SIGTERM), which would otherwise look like an error.
        const sigExit =
          signal === "SIGINT" ||
          signal === "SIGTERM" ||
          code === 130 ||
          code === 143 ||
          stopping;
        // A signal-terminated child reports code === null, so only treat that
        // as clean when it's an expected shutdown (sigExit). An unexpected
        // SIGKILL/SIGSEGV must still surface as an error.
        const exitedCleanly = code === 0 || sigExit;
        if (!exitedCleanly && !settled) {
          settled = true;
          cleanupSignalHandlers();
          stopAll();
          reject(
            new Error(
              `Command failed with code ${String(code)}: ${command?.cmd ?? "unknown"} ${command?.args.join(" ") ?? ""}`,
            ),
          );
          return;
        }

        if (closedCount >= processes.length && !settled) {
          settled = true;
          cleanupSignalHandlers();
          if (shutdownTimer) clearTimeout(shutdownTimer);
          resolve();
        }
      });
    });
  });
}
