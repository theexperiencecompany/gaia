/**
 * Next.js Standalone Server Module
 *
 * Manages the embedded Next.js standalone server that powers
 * the renderer in production builds. The server runs as a
 * child process on a dynamically chosen port.
 *
 * In development the web app is served by the external
 * `nx dev web` process, so this module is not used.
 *
 * @module server
 */

import { createServer } from "node:net";
import { join } from "node:path";
import {
  app,
  BrowserWindow,
  type UtilityProcess,
  utilityProcess,
} from "electron";
import {
  DEV_SERVER_ORIGIN,
  getWindowRoute,
  isProductionServer,
} from "./server-config";

/** Milliseconds to wait for the server to report ready before proceeding. */
const SERVER_STARTUP_TIMEOUT_MS = 15_000;

/** Grace period after SIGTERM before the server is force-killed (SIGKILL). */
const SERVER_KILL_TIMEOUT_MS = 3_000;

/** Handle to the running Next.js child process. */
let serverProcess: UtilityProcess | null = null;

/**
 * Actual port the server is listening on, confirmed from stdout.
 * 0 means the server has not yet bound a port.
 */
let serverPort = 0;

/** Set to true when a clean shutdown is in progress, suppressing restart. */
let shutdownRequested = false;

/** Number of consecutive unplanned restart attempts since last clean start. */
let restartAttempts = 0;
const MAX_RESTART_ATTEMPTS = 3;

/**
 * Check whether a given TCP port is available on localhost.
 *
 * @param port - The port number to test.
 * @returns `true` if the port is free.
 */
async function isPortAvailable(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = createServer();
    server.once("error", () => {
      server.close();
      resolve(false);
    });
    server.once("listening", () => {
      server.close();
      resolve(true);
    });
    server.listen(port, "localhost");
  });
}

/**
 * Find an available port, trying the preferred port first then
 * falling back through a short candidate list.
 */
async function findAvailablePort(): Promise<number> {
  const candidates = [5174, 5175, 5176, 5177, 5178, 5179, 5180];
  for (const port of candidates) {
    if (await isPortAvailable(port)) return port;
  }
  // Fall back to an OS-assigned port if all candidates are taken.
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "localhost", () => {
      const { port } = server.address() as { port: number };
      server.close(() => resolve(port));
    });
  });
}

/**
 * Get the base URL of the running Next.js server.
 *
 * In development the external Next.js dev server runs on port 3000.
 *
 * @returns URL string like `http://localhost:5174` (prod) or `http://localhost:3000` (dev).
 */
export function getServerUrl(): string {
  if (!isProductionServer()) return DEV_SERVER_ORIGIN;
  return `http://localhost:${serverPort}`;
}

/**
 * Start the Next.js standalone server as a child process.
 *
 * Selects a port via `findAvailablePort()` and passes it explicitly.
 * The actual bound port is then confirmed by parsing Next.js's stdout
 * before the promise resolves, so `getServerUrl()` always reflects the
 * real port even if a TOCTOU race caused Next.js to land on a different one.
 *
 * Rejects if:
 * - The child process fails to spawn (ENOENT, EACCES, etc.)
 * - The process exits before printing "Ready"
 * - The startup timeout (15 s) elapses and no port was parsed from stdout
 *
 * @throws If the server cannot be started.
 */
export async function startNextServer(): Promise<void> {
  shutdownRequested = false;
  serverPort = 0;

  const chosenPort = await findAvailablePort();

  const resourcesPath = app.isPackaged
    ? join(process.resourcesPath, "next-server")
    : join(__dirname, "../../web/.next/standalone");

  const serverPath = join(resourcesPath, "apps/web/server.js");

  return new Promise((resolve, reject) => {
    console.log(`Starting Next.js server on port ${chosenPort}...`);
    console.log(`Server path: ${serverPath}`);

    // utilityProcess runs server.js on Electron's bundled Node inside a
    // proper helper process: no reliance on PATH `node` (absent in
    // Finder-launched apps) and no bouncing "exec" Dock icon, which spawning
    // process.execPath with ELECTRON_RUN_AS_NODE causes on macOS.
    serverProcess = utilityProcess.fork(serverPath, [], {
      serviceName: "GAIA Next.js server",
      env: {
        ...process.env,
        PORT: String(chosenPort),
        HOSTNAME: "localhost",
        NODE_ENV: "production",
      },
      cwd: resourcesPath,
      stdio: "pipe",
    });

    let resolved = false;

    serverProcess.stdout?.on("data", (data: Buffer) => {
      const message = data.toString();
      console.log("[Next.js]", message);

      if (resolved) return;

      // Parse the actual bound port from Next.js startup output,
      // e.g. "- Local:  http://localhost:49821"
      // This arrives before the "Ready" line, so serverPort is set
      // before we resolve.
      if (serverPort === 0) {
        const match = message.match(/localhost:(\d+)/);
        if (match) {
          serverPort = parseInt(match[1], 10);
          console.log(`[Main] Next.js bound to port ${serverPort}`);
        }
      }

      if (message.includes("Ready") || message.includes("started server")) {
        if (serverPort === 0) {
          resolved = true;
          reject(
            new Error(
              "Next.js reported ready but bound port could not be parsed from stdout",
            ),
          );
          return;
        }
        resolved = true;
        resolve();
      }
    });

    serverProcess.stderr?.on("data", (data: Buffer) => {
      console.error("[Next.js Error]", data.toString());
    });

    serverProcess.on("exit", (code) => {
      if (!resolved) {
        // Exited before printing "Ready" — genuine startup failure.
        console.error(`Next.js server exited during startup with code ${code}`);
        resolved = true;
        serverProcess = null;
        reject(
          new Error(
            `Next.js server exited with code ${code} before becoming ready`,
          ),
        );
        return;
      }

      serverProcess = null;

      if (shutdownRequested) return; // expected clean shutdown

      // Unexpected post-startup crash — attempt to recover.
      console.error(`Next.js server crashed unexpectedly (code ${code})`);

      if (restartAttempts >= MAX_RESTART_ATTEMPTS) {
        console.error(
          `Max restart attempts (${MAX_RESTART_ATTEMPTS}) reached, giving up`,
        );
        return;
      }

      restartAttempts++;
      console.log(
        `Restarting Next.js server (attempt ${restartAttempts}/${MAX_RESTART_ATTEMPTS})...`,
      );

      startNextServer()
        .then(() => {
          restartAttempts = 0;
          const newUrl = getServerUrl();
          // Re-navigate each window to ITS OWN route. A blanket reload to
          // /desktop-login would send the wake-word listener and the popup
          // islands to the wrong page, silently breaking them until restart.
          for (const win of BrowserWindow.getAllWindows()) {
            if (win.isDestroyed()) continue;
            const route = getWindowRoute(win);
            if (!route) continue; // splash / untracked windows keep their page
            win.loadURL(`${newUrl}${route}`).catch(console.error);
          }
        })
        .catch((err) => {
          console.error("Failed to restart Next.js server:", err);
        });
    });

    // Hard timeout: if the port was parsed but "Ready" never arrived,
    // proceed cautiously. If the port was never parsed, the server
    // cannot be reached at all — reject cleanly.
    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        if (serverPort > 0) {
          console.warn("Server startup timeout — port known, assuming ready");
          resolve();
        } else {
          console.error(
            "Server startup timeout — port never parsed from stdout",
          );
          reject(new Error("Server startup timed out without binding a port"));
        }
      }
    }, SERVER_STARTUP_TIMEOUT_MS);
  });
}

/**
 * Stop the Next.js server and wait for the process to exit.
 *
 * `UtilityProcess.kill()` sends SIGTERM. If the process has not exited
 * within 3 seconds it is force-killed with SIGKILL via its pid.
 */
export async function stopNextServer(): Promise<void> {
  if (!serverProcess) return;

  shutdownRequested = true;
  console.log("Stopping Next.js server...");

  return new Promise((resolve) => {
    const proc = serverProcess as UtilityProcess;
    serverProcess = null;

    const killTimeout = setTimeout(() => {
      try {
        if (proc.pid) process.kill(proc.pid, "SIGKILL");
      } catch {
        // Process already exited
      }
    }, SERVER_KILL_TIMEOUT_MS);

    proc.once("exit", () => {
      clearTimeout(killTimeout);
      resolve();
    });

    proc.kill();
  });
}
