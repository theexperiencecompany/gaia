import { spawn } from "child_process";

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
      for (let i = 0; i < processes.length; i++) {
        const proc = processes[i];
        const command = commands[i];
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
        for (let i = 0; i < processes.length; i++) {
          const proc = processes[i];
          const command = commands[i];
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

      proc.on("close", (code) => {
        closedCount += 1;

        const exitedCleanly = code === null || code === 0;
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
