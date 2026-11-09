/**
 * The local processes a detached `gaia dev` leaves running: its PID file, and
 * stopping it by that PID or, with --force-ports, by the ports it listens on.
 * @module lib/dev-processes
 */

import * as fs from "fs";
import * as path from "path";
import { runCommand } from "./child-process.js";
import { DEFAULT_API_PORT, DEFAULT_WEB_PORT } from "./endpoints.js";

export const DEV_LOG_FILE = "dev-start.log";
export const DEV_PID_FILE = ".gaia-dev.pid";

/** How long a SIGTERM'd dev session gets before SIGKILL. */
const DEV_STOP_GRACE_MS = 800;

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export function readStoredDevPid(repoPath: string): number | null {
  const pidPath = path.join(repoPath, DEV_PID_FILE);
  if (!fs.existsSync(pidPath)) return null;
  try {
    const pid = Number.parseInt(fs.readFileSync(pidPath, "utf-8").trim(), 10);
    return Number.isNaN(pid) || pid <= 0 ? null : pid;
  } catch {
    return null;
  }
}

export function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    return code === "EPERM";
  }
}

/** Stop `gaia dev`'s local processes: by its stored PID, or by port with forcePorts. */
export async function stopDeveloperProcesses(
  repoPath: string,
  onStatus?: (status: string) => void,
  portOverrides?: Record<number, number>,
  forcePorts?: boolean,
): Promise<void> {
  onStatus?.("Stopping GAIA-managed local processes (safe mode)…");
  const pid = readStoredDevPid(repoPath);
  const killedByPid = pid !== null && (await killDevProcess(repoPath, pid));
  try {
    fs.unlinkSync(path.join(repoPath, DEV_PID_FILE));
  } catch {
    // The PID file may never have existed.
  }
  if (killedByPid) return;

  // Fall back to port-based cleanup only when explicitly requested.
  if (forcePorts) {
    onStatus?.("No GAIA PID found. Force-stopping listeners on app ports…");
    await killPortListeners(repoPath, [
      portOverrides?.[DEFAULT_API_PORT] ?? DEFAULT_API_PORT,
      portOverrides?.[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT,
    ]);
    return;
  }
  onStatus?.(
    pid !== null
      ? "Stored GAIA PID is stale. Skipping port cleanup in safe mode. Use `gaia stop --force-ports` for aggressive cleanup."
      : "No GAIA-managed PID found. Skipping port cleanup in safe mode. Use `gaia stop --force-ports` for aggressive cleanup.",
  );
}

/** Terminate a detached `gaia dev` session (its process group); false when it was not running. */
async function killDevProcess(repoPath: string, pid: number): Promise<boolean> {
  if (!isPidAlive(pid)) return false;
  try {
    if (process.platform === "win32") {
      await runCommand("taskkill", ["/PID", String(pid), "/T", "/F"], {
        cwd: repoPath,
      });
      return true;
    }
    signalGroup(pid, "SIGTERM");
    await delay(DEV_STOP_GRACE_MS);
    if (isPidAlive(pid)) signalGroup(pid, "SIGKILL");
    return true;
  } catch {
    // The process exited between the check and the signal.
    return false;
  }
}

/** Signal a process group, or the lone process when it leads no group. */
function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pid, signal);
  } catch {
    process.kill(pid, signal);
  }
}

/** Kill whatever listens on each port (--force-ports; may hit non-GAIA processes). */
async function killPortListeners(
  repoPath: string,
  ports: number[],
): Promise<void> {
  await Promise.all(
    ports.map((port) => {
      const [cmd, args] =
        process.platform === "win32"
          ? [
              "powershell",
              [
                "-Command",
                `Get-NetTCPConnection -LocalPort ${port} -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }`,
              ],
            ]
          : [
              "sh",
              [
                "-c",
                `lsof -ti :${port} -sTCP:LISTEN | xargs kill 2>/dev/null || true`,
              ],
            ];
      return runCommand(cmd, args, { cwd: repoPath });
    }),
  );
}
