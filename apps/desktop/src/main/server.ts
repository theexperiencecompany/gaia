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

import { type ChildProcess, spawn } from "node:child_process";
import { createServer } from "node:net";
import { join } from "node:path";
import { app } from "electron";
import getPort from "get-port";

/** Handle to the running Next.js child process. */
let serverProcess: ChildProcess | null = null;

/** TCP port the server is listening on. */
let serverPort = 5174;

/**
 * Check whether a given TCP port is available on localhost.
 *
 * Opens a temporary `net.Server` to test binding — if the
 * port is already in use the `error` event fires immediately.
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
 * Find an available port for the server.
 *
 * Tries the preferred port (5174) first for deterministic
 * behaviour, then falls back to `get-port` with a short
 * candidate list.
 *
 * @returns An available port number.
 */
async function findAvailablePort(): Promise<number> {
  const preferredPort = 5174;

  if (await isPortAvailable(preferredPort)) {
    return preferredPort;
  }

  console.log(`Port ${preferredPort} in use, finding alternative...`);
  return await getPort({ port: [5175, 5176, 5177, 5178, 5179, 5180] });
}

/**
 * Get the base URL of the running Next.js server.
 *
 * In development the external Next.js dev server runs on port 3000.
 *
 * @returns URL string like `http://localhost:5174` (prod) or `http://localhost:3000` (dev).
 */
export function getServerUrl(): string {
  if (process.env.NODE_ENV !== "production") {
    return "http://localhost:3000";
  }
  return `http://localhost:${serverPort}`;
}

/**
 * Start the Next.js standalone server as a child process.
 *
 * Resolves once the server prints a "Ready" or "started server"
 * message to stdout, or after an 8-second timeout (whichever
 * comes first). The timeout is intentionally generous — the
 * main window's polling logic provides additional wait time.
 *
 * @throws If the child process fails to spawn.
 */
export async function startNextServer(): Promise<void> {
  serverPort = await findAvailablePort();

  const resourcesPath = app.isPackaged
    ? join(process.resourcesPath, "next-server")
    : join(__dirname, "../../web/.next/standalone");

  const serverPath = join(resourcesPath, "apps/web/server.js");

  return new Promise((resolve, reject) => {
    console.log(`Starting Next.js server on port ${serverPort}...`);
    console.log(`Server path: ${serverPath}`);

    serverProcess = spawn("node", [serverPath], {
      env: {
        ...process.env,
        PORT: String(serverPort),
        HOSTNAME: "localhost",
        NODE_ENV: "production",
      },
      cwd: resourcesPath,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let resolved = false;

    serverProcess.stdout?.on("data", (data: Buffer) => {
      const message = data.toString();
      console.log("[Next.js]", message);

      if (
        !resolved &&
        (message.includes("Ready") || message.includes("started server"))
      ) {
        resolved = true;
        resolve();
      }
    });

    serverProcess.stderr?.on("data", (data: Buffer) => {
      console.error("[Next.js Error]", data.toString());
    });

    serverProcess.on("error", (error) => {
      console.error("Failed to start Next.js server:", error);
      if (!resolved) {
        resolved = true;
        reject(error);
      }
    });

    serverProcess.on("close", (code) => {
      console.log(`Next.js server exited with code ${code}`);
      serverProcess = null;
    });

    setTimeout(() => {
      if (!resolved && serverProcess) {
        console.warn("Server startup timeout - assuming ready");
        resolved = true;
        resolve();
      }
    }, 8000);
  });
}

/**
 * Stop the Next.js server and wait for the process to exit.
 *
 * Sends `SIGTERM` first. On Windows (where `SIGTERM` may be
 * ignored) a `SIGKILL` follow-up is scheduled after 3 seconds.
 */
export async function stopNextServer(): Promise<void> {
  if (!serverProcess) return;

  console.log("Stopping Next.js server...");

  return new Promise((resolve) => {
    const proc = serverProcess as ChildProcess;
    serverProcess = null;

    proc.once("exit", () => {
      resolve();
    });

    proc.kill("SIGTERM");

    if (process.platform === "win32") {
      setTimeout(() => {
        try {
          proc.kill("SIGKILL");
        } catch {
          // Process already exited
        }
      }, 3000);
    }
  });
}
