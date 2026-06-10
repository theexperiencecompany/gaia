/**
 * Window URL Loading Module
 *
 * Shared helper for navigating any BrowserWindow to a route on the
 * app's web server once that server is reachable. In development it
 * polls the external dev server on `localhost:3000`; in production it
 * polls the embedded Next.js server via the `serverReady` callback.
 *
 * @module windows/load-url
 */

import { createConnection } from "node:net";
import { app, type BrowserWindow } from "electron";
import { getServerUrl } from "../server";

/** Development web server origin (Next.js dev server). */
const DEV_SERVER_URL = "http://localhost:3000";

/** Development web server port used for TCP readiness polling. */
const DEV_SERVER_PORT = 3000;

/** Delay between readiness polls, in milliseconds. */
const POLL_INTERVAL_MS = 100;

/** Maximum production readiness polls (50 × 100 ms = 5 s). */
const PROD_MAX_ATTEMPTS = 50;

/** Maximum development readiness polls (100 × 100 ms = 10 s). */
const DEV_MAX_ATTEMPTS = 100;

/** Whether the app is running against the embedded production server. */
export function isProductionServer(): boolean {
  return process.env.NODE_ENV === "production" || app.isPackaged;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Probe the dev server with a short-lived TCP connection. */
function probeDevServer(): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    const socket = createConnection({
      port: DEV_SERVER_PORT,
      host: "localhost",
    });
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => {
      socket.destroy();
      resolve(false);
    });
    setTimeout(() => {
      socket.destroy();
      resolve(false);
    }, POLL_INTERVAL_MS);
  });
}

async function loadRoute(
  win: BrowserWindow | null,
  baseUrl: string,
  path: string,
): Promise<void> {
  try {
    await win?.loadURL(`${baseUrl}${path}`);
  } catch (err) {
    console.error(`[Main] Failed to load URL ${baseUrl}${path}:`, err);
  }
}

/**
 * Navigate `win` to `path` on the app web server once it is reachable.
 *
 * Resolves after the navigation has been attempted (successfully or
 * not). If the server never becomes ready within the polling budget,
 * the navigation is attempted anyway as a best-effort fallback.
 *
 * @param win - Target window (ignored if destroyed in the meantime).
 * @param path - Absolute route path, e.g. `"/desktop-login"`.
 * @param serverReady - Returns `true` once the production server is up.
 *   Ignored in development mode.
 */
export async function loadAppRoute(
  win: BrowserWindow,
  path: string,
  serverReady: () => boolean,
): Promise<void> {
  if (isProductionServer()) {
    for (let i = 0; i < PROD_MAX_ATTEMPTS; i++) {
      if (serverReady()) {
        // Read the URL only after the server is ready so that the port
        // reflects the actual bound port (which may differ from the
        // default when the server picked an alternative port).
        const serverUrl = getServerUrl();
        console.log("[Main] Server is ready, loading URL:", serverUrl + path);
        await loadRoute(win, serverUrl, path);
        return;
      }
      await delay(POLL_INTERVAL_MS);
    }

    console.log("[Main] Server wait timeout, attempting to load anyway");
    await loadRoute(win, getServerUrl(), path);
    return;
  }

  console.log("[Main] Waiting for dev server at", DEV_SERVER_URL);

  for (let i = 0; i < DEV_MAX_ATTEMPTS; i++) {
    if (await probeDevServer()) {
      console.log("[Main] Dev server ready, loading...");
      await loadRoute(win, DEV_SERVER_URL, path);
      return;
    }
    await delay(POLL_INTERVAL_MS);
  }

  console.log("[Main] Dev server wait timeout, attempting to load anyway");
  await loadRoute(win, DEV_SERVER_URL, path);
}
